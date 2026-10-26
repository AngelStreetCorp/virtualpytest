# Free cloud starter

This is the cheapest way to show VirtualPyTest in the cloud. It is a demo and test setup, not a production system. Free services sleep when idle and have small limits.

<div data-technical>

Free services can also lose data kept in memory.

</div>

## Recommended architecture

The frontend and server run on Render's free web services. The database and login run on Supabase's free plan. The device host runs on a small Linux virtual machine (VM), because it has to stay on to reach the devices.

<div data-technical>

Render's free services sleep, so they cannot run the host. For a cloud-only demo with virtual devices, a small VM can run the host instead. A host must run all the time, and it may need emulators, USB, Bluetooth, IR or capture devices.

```text
Render free web services
  frontend + backend server
          │
          ├── Supabase Free: Postgres, Auth, REST, Storage
          ├── Render Key Value: Redis-compatible cache
          └── Linux VM: VirtualPyTest host and virtual devices
```

The host is a Linux VM rather than a Render Free service. Render Free services sleep after inactivity and do not support the private-service shape needed for a continuously reachable host.

</div>

## Services and free-tier choices

| Part | Starter choice | Notes |
|---|---|---|
| Frontend | Render Free Web Service or Static Site | Sleeps when idle; first request can be slow. |
| Backend server | Render Free Web Service | Use hosted Supabase and external storage. |
| Database/Auth | [Supabase Free](https://supabase.com) | Create a project and apply our schema. |
| Redis | Render Free Key Value | Redis-compatible, but in-memory and disposable on restart. |
| Object storage | Supabase Storage or an S3-compatible provider | Do not use local container storage on a free web service. |
| Host | A Linux VM | Provider is interchangeable; see the host options below. |
| Grafana | Optional | Omit for the smallest demo or run it on the VM. |

Read [Render's free-tier limitations](https://render.com/docs/free) before you present this as a lasting service.

<div data-technical>

Render's free plans cover web services, static sites, Postgres and Key Value. Free Postgres expires after 30 days, so this guide uses Supabase for the database.

</div>

## 1. Create Supabase

Create a Supabase project and note its keys. Then set up the database. Follow [Using a cloud Supabase project](../get-started/supabase.md#using-a-cloud-supabase-project).

Keep the service key and database password only in the server and host settings.

<div data-technical>

Never put them in the frontend settings. Record the project URL, public/anon key, server-side service key, JWT secret and database connection string. Apply the schema once:

```bash
./setup/db/apply_schema.sh \
  "postgresql://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres"
```

</div>

## 2. Deploy the frontend and server

Set up the frontend and server on Render with the [managed cloud guide](../get-started/cloud-setup.md).

<div data-technical>

Give the server its Supabase settings, then point the frontend at the server's address. Set the server's Supabase variables in Render. Use the published GHCR image tag when you create an image-backed service. Or connect Render to the repository and build the Dockerfile.

</div>

## 3. Choose a Linux VM for the host

The host can run on any Linux VM you can reach.

### AWS

AWS has a free trial of a small ARM Linux VM for eligible accounts. It ends after a time and needs billing set up, and the software must run on ARM. Set a billing alarm before you start it. See the [AWS free-tier documentation](https://aws.amazon.com/ec2/faqs/).

<div data-technical>

The trial instance type is T4g and needs ARM64 images.

</div>

### Google Cloud

Google's always-free VM is too small for the full host stack. Use it only for a small or occasional virtual-device demo. See the [Google Cloud Free Tier](https://cloud.google.com/free/docs/free-cloud-features).

<div data-technical>

The always-free instance is `e2-micro`, with 1 GiB RAM and a fractional CPU.

</div>

### Oracle Cloud

Oracle's always-free plan has the most capacity, but availability and account creation vary by region. See [Oracle Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).

<div data-technical>

The Ampere VM is ARM64, so the same multi-architecture image requirement applies.

</div>

## 4. Connect the host

On the Linux VM, add the host as described in [Add a host](../get-started/add-a-host.md). Protect the host with a firewall or VPN. Do not open its control and VNC ports to the whole internet.

<div data-technical>

Use the same cloud server, database and storage settings as the server. Configure the host with the same cloud server URL, Supabase URL, public key, service key and storage settings used by the server.

</div>

## What this starter does not promise

- Render Free is not always on and is not production hosting.
- A free VM may be reclaimed, suspended, or limited by regional capacity.

<div data-technical>

Physical HDMI, USB, Bluetooth, IR and capture hardware must stay attached to a machine that can reach it. Grafana is optional in the free showcase. The full Compose installation remains the supported path for the complete self-hosted platform.

</div>
