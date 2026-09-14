#!/usr/bin/env python3
"""Apply the BlueZ external-app CCCD persistence patch in-place.

Run with the path to gatt-database.c as the only argument. Idempotent:
running it twice is a no-op (it detects the marker comments).

Always make a backup of the original file before running this script
(the project keeps gatt-database.c.orig next to the original).
"""
import re
import sys

MARKER = '/* host1 patch: CCC persistence */'

# Helper functions inserted near the existing find_ccc_state() function.
# v2: indexes the on-disk [Cccs] section by (service-uuid, characteristic-uuid)
# instead of raw handle. Raw handles drift when the GATT app re-registers
# (BlueZ allocates them sequentially based on what's already in the local DB,
# so adding/removing services or even just timing between core-service and
# external-app loads shifts every subsequent handle). UUIDs are stable.
HELPERS = '''
/* host1 patch: CCC persistence */
/* ===========================================================================
 * CCCD persistence for external GATT applications
 *
 * Extends /var/lib/bluetooth/<adapter>/<peer>/info with a [Cccs] section.
 * Each entry is keyed by "<service-uuid>:<characteristic-uuid>" so the
 * persistence survives BlueZ restart even when the GATT db gets different
 * raw handles allocated. Values are the 16-bit little-endian CCC value
 * (0x0001 = notify, 0x0002 = indicate, 0x0003 = both).
 *
 * On a CCC write, we walk up from the CCC descriptor to its parent
 * characteristic and parent service, save (svc_uuid, chrc_uuid, value).
 *
 * On external-app re-registration or bonded-device reconnect, we walk
 * the current GATT db, find each persisted (svc_uuid, chrc_uuid) pair,
 * look up the CURRENT CCC descriptor handle for that characteristic, and
 * push that handle/value pair into device_state->ccc_states so BlueZ's
 * notify path will deliver notifications to the bonded client even
 * though the client never re-wrote the CCCD.
 * ===========================================================================
 */

/* --- Walking helpers --------------------------------------------------- */

struct host1_find_chrc_for_ccc {
\tuint16_t ccc_handle;
\tbt_uuid_t chrc_uuid;
\tbool found;
};

static void host1_check_desc_handle(struct gatt_db_attribute *desc,
\t\t\t\t\t\tvoid *user_data)
{
\tstruct host1_find_chrc_for_ccc *data = user_data;

\tif (data->found)
\t\treturn;

\tif (gatt_db_attribute_get_handle(desc) == data->ccc_handle)
\t\tdata->found = true;
}

static void host1_check_chrc_for_ccc(struct gatt_db_attribute *chrc,
\t\t\t\t\t\tvoid *user_data)
{
\tstruct host1_find_chrc_for_ccc *data = user_data;
\tbool was_found = data->found;
\tbt_uuid_t chrc_uuid;

\tif (data->found)
\t\treturn;

\tgatt_db_service_foreach_desc(chrc, host1_check_desc_handle, data);

\tif (data->found && !was_found) {
\t\tif (gatt_db_attribute_get_char_data(chrc, NULL, NULL, NULL,
\t\t\t\t\t\tNULL, &chrc_uuid))
\t\t\tdata->chrc_uuid = chrc_uuid;
\t}
}

/* Given a CCC descriptor handle, find (svc_uuid, chrc_uuid) of its
 * parent characteristic. Returns true on success. */
static bool host1_uuids_for_ccc(struct gatt_db *db, uint16_t ccc_handle,
\t\t\t\t\tbt_uuid_t *svc_uuid,
\t\t\t\t\tbt_uuid_t *chrc_uuid)
{
\tstruct gatt_db_attribute *ccc_attr, *service;
\tstruct host1_find_chrc_for_ccc data;
\tuint16_t svc_start = 0, svc_end = 0;

\tif (!db || !ccc_handle)
\t\treturn false;

\tccc_attr = gatt_db_get_attribute(db, ccc_handle);
\tif (!ccc_attr)
\t\treturn false;

\tif (!gatt_db_attribute_get_service_uuid(ccc_attr, svc_uuid))
\t\treturn false;

\tif (!gatt_db_attribute_get_service_handles(ccc_attr,
\t\t\t\t\t&svc_start, &svc_end))
\t\treturn false;

\tservice = gatt_db_get_service(db, svc_start);
\tif (!service)
\t\treturn false;

\tmemset(&data, 0, sizeof(data));
\tdata.ccc_handle = ccc_handle;
\tdata.found = false;

\tgatt_db_service_foreach_char(service, host1_check_chrc_for_ccc, &data);

\tif (!data.found)
\t\treturn false;

\t*chrc_uuid = data.chrc_uuid;
\treturn true;
}

struct host1_find_ccc_handle {
\tconst bt_uuid_t *target_chrc_uuid;
\tuint16_t result_ccc_handle;
};

static void host1_check_desc_is_ccc(struct gatt_db_attribute *desc,
\t\t\t\t\t\tvoid *user_data)
{
\tstruct host1_find_ccc_handle *data = user_data;
\tconst bt_uuid_t *uuid;
\tbt_uuid_t ccc_uuid;

\tif (data->result_ccc_handle)
\t\treturn;

\tbt_uuid16_create(&ccc_uuid, GATT_CLIENT_CHARAC_CFG_UUID);
\tuuid = gatt_db_attribute_get_type(desc);
\tif (!uuid)
\t\treturn;

\tif (!bt_uuid_cmp(uuid, &ccc_uuid))
\t\tdata->result_ccc_handle =
\t\t\t\tgatt_db_attribute_get_handle(desc);
}

static void host1_check_chrc_uuid(struct gatt_db_attribute *chrc,
\t\t\t\t\t\tvoid *user_data)
{
\tstruct host1_find_ccc_handle *data = user_data;
\tbt_uuid_t chrc_uuid;

\tif (data->result_ccc_handle)
\t\treturn;

\tif (!gatt_db_attribute_get_char_data(chrc, NULL, NULL, NULL,
\t\t\t\t\t\tNULL, &chrc_uuid))
\t\treturn;

\tif (bt_uuid_cmp(&chrc_uuid, data->target_chrc_uuid))
\t\treturn;

\tgatt_db_service_foreach_desc(chrc, host1_check_desc_is_ccc, data);
}

struct host1_find_ccc_outer {
\tconst bt_uuid_t *target_svc_uuid;
\tconst bt_uuid_t *target_chrc_uuid;
\tuint16_t result;
};

static void host1_check_svc_uuid(struct gatt_db_attribute *svc,
\t\t\t\t\tvoid *user_data)
{
\tstruct host1_find_ccc_outer *data = user_data;
\tbt_uuid_t svc_uuid;
\tstruct host1_find_ccc_handle inner;

\tif (data->result)
\t\treturn;

\tif (!gatt_db_attribute_get_service_uuid(svc, &svc_uuid))
\t\treturn;

\tif (bt_uuid_cmp(&svc_uuid, data->target_svc_uuid))
\t\treturn;

\tinner.target_chrc_uuid = data->target_chrc_uuid;
\tinner.result_ccc_handle = 0;
\tgatt_db_service_foreach_char(svc, host1_check_chrc_uuid, &inner);

\tdata->result = inner.result_ccc_handle;
}

/* Returns the current CCC descriptor handle for the characteristic with
 * the given (svc_uuid, chrc_uuid) in the local GATT db, or 0 if not
 * found. */
static uint16_t host1_ccc_handle_for_uuids(struct gatt_db *db,
\t\t\t\t\t\tconst bt_uuid_t *svc_uuid,
\t\t\t\t\t\tconst bt_uuid_t *chrc_uuid)
{
\tstruct host1_find_ccc_outer data;

\tdata.target_svc_uuid = svc_uuid;
\tdata.target_chrc_uuid = chrc_uuid;
\tdata.result = 0;
\tgatt_db_foreach_service(db, NULL, host1_check_svc_uuid, &data);
\treturn data.result;
}

/* --- Persistence -------------------------------------------------------- */

static void store_ccc_persistent(struct btd_gatt_database *database,
\t\t\t\t\tconst bdaddr_t *addr,
\t\t\t\t\tuint16_t ccc_handle, uint16_t value)
{
\tchar filename[PATH_MAX];
\tchar addr_str[18];
\tchar svc_str[37], chrc_str[37];
\tchar key[80], val_str[8];
\tbt_uuid_t svc_uuid, chrc_uuid;
\tGKeyFile *kf;
\tGError *gerr = NULL;
\tchar *str;
\tgsize length = 0;

\tif (!database || !addr || !ccc_handle)
\t\treturn;

\tif (!host1_uuids_for_ccc(database->db, ccc_handle,
\t\t\t\t\t&svc_uuid, &chrc_uuid))
\t\treturn;

\tbt_uuid_to_string(&svc_uuid, svc_str, sizeof(svc_str));
\tbt_uuid_to_string(&chrc_uuid, chrc_str, sizeof(chrc_str));

\tba2str(addr, addr_str);
\tcreate_filename(filename, PATH_MAX, "/%s/%s/info",
\t\t\tbtd_adapter_get_storage_dir(database->adapter),
\t\t\taddr_str);

\tkf = g_key_file_new();
\tif (!g_key_file_load_from_file(kf, filename, 0, &gerr))
\t\tg_clear_error(&gerr);

\tsnprintf(key, sizeof(key), "%s:%s", svc_str, chrc_str);
\tsnprintf(val_str, sizeof(val_str), "0x%04x", value);
\tg_key_file_set_string(kf, "Cccs", key, val_str);

\tcreate_file(filename, 0600);

\tstr = g_key_file_to_data(kf, &length, NULL);
\tif (str) {
\t\tg_file_set_contents(filename, str, length, NULL);
\t\tg_free(str);
\t}
\tg_key_file_free(kf);

\tDBG("Persisted CCC %s/%s = 0x%04x for %s",
\t\t\t\t\tsvc_str, chrc_str, value, addr_str);
}

static void load_ccc_persistent(struct btd_gatt_database *database,
\t\t\t\t\tconst bdaddr_t *addr,
\t\t\t\t\tuint8_t addr_type)
{
\tchar filename[PATH_MAX];
\tchar addr_str[18];
\tGKeyFile *kf;
\tGError *gerr = NULL;
\tchar **keys = NULL;
\tgsize n_keys = 0, i;
\tstruct device_state *dev_state;

\tif (!database || !addr)
\t\treturn;

\tba2str(addr, addr_str);
\tcreate_filename(filename, PATH_MAX, "/%s/%s/info",
\t\t\tbtd_adapter_get_storage_dir(database->adapter),
\t\t\taddr_str);

\tkf = g_key_file_new();
\tif (!g_key_file_load_from_file(kf, filename, 0, &gerr)) {
\t\tg_clear_error(&gerr);
\t\tg_key_file_free(kf);
\t\treturn;
\t}

\tif (!g_key_file_has_group(kf, "Cccs")) {
\t\tg_key_file_free(kf);
\t\treturn;
\t}

\tdev_state = find_device_state(database, addr, addr_type);
\tif (!dev_state) {
\t\tdev_state = device_state_create(database, addr, addr_type);
\t\tqueue_push_tail(database->device_states, dev_state);
\t}

\tkeys = g_key_file_get_keys(kf, "Cccs", &n_keys, NULL);
\tfor (i = 0; keys && i < n_keys; i++) {
\t\tchar *val_str, *colon;
\t\tchar svc_str[37], chrc_str[37];
\t\tbt_uuid_t svc_uuid, chrc_uuid;
\t\tuint16_t value, ccc_handle;
\t\tstruct ccc_state *ccc;
\t\tsize_t svc_len;

\t\tcolon = strchr(keys[i], ':');
\t\tif (!colon)
\t\t\tcontinue;

\t\tsvc_len = colon - keys[i];
\t\tif (svc_len >= sizeof(svc_str))
\t\t\tcontinue;

\t\tmemcpy(svc_str, keys[i], svc_len);
\t\tsvc_str[svc_len] = '\\0';
\t\tstrncpy(chrc_str, colon + 1, sizeof(chrc_str) - 1);
\t\tchrc_str[sizeof(chrc_str) - 1] = '\\0';

\t\tif (bt_string_to_uuid(&svc_uuid, svc_str) < 0)
\t\t\tcontinue;
\t\tif (bt_string_to_uuid(&chrc_uuid, chrc_str) < 0)
\t\t\tcontinue;

\t\tval_str = g_key_file_get_string(kf, "Cccs", keys[i], NULL);
\t\tvalue = (uint16_t) (val_str ?
\t\t\t\t\tstrtoul(val_str, NULL, 0) : 0);
\t\tg_free(val_str);
\t\tif (!value)
\t\t\tcontinue;

\t\tccc_handle = host1_ccc_handle_for_uuids(database->db,
\t\t\t\t\t\t&svc_uuid, &chrc_uuid);
\t\tif (!ccc_handle) {
\t\t\tDBG("CCC for %s/%s not found in current GATT db, "
\t\t\t\t"skipping", svc_str, chrc_str);
\t\t\tcontinue;
\t\t}

\t\tccc = find_ccc_state(dev_state, ccc_handle);
\t\tif (!ccc) {
\t\t\tccc = new0(struct ccc_state, 1);
\t\t\tccc->handle = ccc_handle;
\t\t\tqueue_push_tail(dev_state->ccc_states, ccc);
\t\t}
\t\tccc->value = value;

\t\tDBG("Loaded CCC %s/%s -> handle 0x%04x = 0x%04x for %s",
\t\t\t\tsvc_str, chrc_str, ccc_handle, value, addr_str);
\t}
\tg_strfreev(keys);
\tg_key_file_free(kf);
}

static void load_ccc_for_device_cb(struct btd_device *device, void *user_data)
{
\tstruct btd_gatt_database *database = user_data;

\tload_ccc_persistent(database, device_get_address(device),
\t\t\tdevice_get_le_address_type(device));
}
/* host1 patch end */

'''


def main():
    if len(sys.argv) != 2:
        print('usage: apply_ccc_patch.py <path-to-gatt-database.c>',
              file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    with open(path) as f:
        src = f.read()

    if MARKER in src:
        print('patch already applied, nothing to do')
        return 0

    # 1. Insert helper functions just before the existing
    #    `static void device_state_free(void *data)` definition.
    anchor = 'static void device_state_free(void *data)\n'
    if anchor not in src:
        print('FATAL: anchor "device_state_free" not found', file=sys.stderr)
        sys.exit(2)
    src = src.replace(anchor, HELPERS + anchor, 1)

    # 2. In `connect_cb`, add a load_ccc_persistent() call right after
    #    `device_attach_att(device, io);`
    connect_anchor = 'device_attach_att(device, io);\n}\n'
    connect_replacement = (
        'device_attach_att(device, io);\n\n'
        '\t/* host1 patch: CCC persistence */\n'
        '\tload_ccc_persistent(btd_adapter_get_database(adapter), &dst, dst_type);\n'
        '}\n'
    )
    if connect_anchor not in src:
        print('FATAL: connect_cb anchor not found', file=sys.stderr)
        sys.exit(3)
    src = src.replace(connect_anchor, connect_replacement, 1)

    # 3. In `gatt_ccc_write_cb`, persist the CCC value right after
    #    `ccc->value = val;`
    write_anchor = (
        '\tif (!ecode)\n'
        '\t\tccc->value = val;\n'
        '\n'
        'done:\n'
    )
    write_replacement = (
        '\tif (!ecode)\n'
        '\t\tccc->value = val;\n'
        '\n'
        '\t/* host1 patch: CCC persistence */\n'
        '\tif (!ecode && att) {\n'
        '\t\tbdaddr_t bdaddr;\n'
        '\t\tuint8_t bdaddr_type;\n'
        '\n'
        '\t\tif (get_dst_info(att, &bdaddr, &bdaddr_type))\n'
        '\t\t\tstore_ccc_persistent(database, &bdaddr,\n'
        '\t\t\t\t\t\thandle, val);\n'
        '\t}\n'
        '\n'
        'done:\n'
    )
    if write_anchor not in src:
        print('FATAL: gatt_ccc_write_cb anchor not found', file=sys.stderr)
        sys.exit(4)
    src = src.replace(write_anchor, write_replacement, 1)

    # 4. In `client_ready_cb`, replay CCCDs after `database_add_app(app)`
    #    succeeds. Insert just before "reply = dbus_message_new_method_return".
    ready_anchor = (
        '\tDBG("GATT application registered: %s:%s", app->owner, app->path);\n'
        '\n'
        '\treply = dbus_message_new_method_return(app->reg);\n'
    )
    ready_replacement = (
        '\tDBG("GATT application registered: %s:%s", app->owner, app->path);\n'
        '\n'
        '\t/* host1 patch: CCC persistence */\n'
        '\tbtd_adapter_for_each_device(app->database->adapter,\n'
        '\t\t\t\tload_ccc_for_device_cb, app->database);\n'
        '\n'
        '\treply = dbus_message_new_method_return(app->reg);\n'
    )
    if ready_anchor not in src:
        print('FATAL: client_ready_cb anchor not found', file=sys.stderr)
        sys.exit(5)
    src = src.replace(ready_anchor, ready_replacement, 1)

    with open(path, 'w') as f:
        f.write(src)
    print('patch applied successfully')


if __name__ == '__main__':
    sys.exit(main() or 0)
