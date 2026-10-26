package io.virtualpytest.app

import android.content.Context
import android.net.wifi.WifiManager
import android.os.Handler
import android.os.Looper
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.NetworkInterface
import java.util.concurrent.atomic.AtomicBoolean

/**
 * The phone's radio end of a remote Tello (TASK-167).
 *
 * The drone is in Wi-Fi *client* mode: it joined this phone's hotspot and took a DHCP
 * lease, so the drone is reachable at an address on the hotspot's subnet. This class
 * holds the drone's SDK conversation over that Wi-Fi and relays it to the host over the
 * Socket.IO channel [PhoneAgentService] already keeps open - the same channel that
 * carries the phone's screen frames, so no second connection is needed.
 *
 * The shape of the drone's SDK is what drives the design:
 *
 *  * A Tello only answers the address:port that sent its first `command` after power-on
 *    (measured on vpt-pi4, 2026-10-13). So there is exactly ONE command socket here, and
 *    the discovery scan has to use it - a scan from a throwaway port would steal the
 *    drone's binding and every later command would time out.
 *  * The drone pushes state and video to FIXED ports (8890 / 11111) of its client. With
 *    several drones on one hotspot they all push to the same two ports, and they are told
 *    apart by their source address.
 *
 * Several drones at once is therefore just several entries in [drones]: one command
 * socket for all of them, one state socket, one video socket, and the source address of
 * each packet says which drone it came from.
 */
class DroneBridge(private val context: Context) {

    companion object {
        private const val TAG = "DroneBridge"

        /** How long a drone may be silent before it is considered gone. */
        private const val DRONE_STALE_MS = 15_000L

        /** How often the phone reports which drones it carries. */
        private const val STATUS_INTERVAL_MS = 10_000L

        /** How long the discovery scan waits for a drone to answer `command`. */
        private const val DISCOVERY_TIMEOUT_MS = 200

        /**
         * How long a drone counts as still there.
         *
         * The drone pushes its state continuously once it is awake and in SDK mode, so a
         * drone that has been silent for a minute is really gone - asleep, or off the
         * hotspot. The host needs to know that: the phone is the FALLBACK path, and a
         * fallback that cannot reach the drone is no fallback at all.
         */
        private const val PRESENCE_WINDOW_MS = 60_000L

        /**
         * How often the phone looks for a drone by itself.
         *
         * The owner turns the hotspot on and powers the drone; the phone notices the
         * hotspot, scans for the drone and reports it to the host. Without this the
         * owner would have to press a button every time the drone comes back.
         */
        private const val AUTO_SCAN_INTERVAL_MS = 60_000L

        /** The address range a phone hotspot hands out on Android (the usual ones). */
        private val HOTSPOT_SUBNETS = listOf("192.168.43.", "192.168.147.", "192.168.49.")

        /**
         * The names Android gives the tethering interface.
         *
         * `ap0` is the tethering interface on most builds, `swlan0` on some, `tether0` on
         * a few. The phone's own Wi-Fi client is `wlan0`/`wlan1`, which is why the names
         * are matched as a prefix and not as "any interface with a private address".
         */
        private val HOTSPOT_INTERFACE_NAMES = listOf("ap", "swlan", "tether")
    }

    /** One drone this phone carries: its address on the hotspot and the label the owner gave it. */
    data class Drone(val label: String, val ip: String) {
        var lastSeenAt: Long = 0L

        /** Is the drone still answering on the hotspot? */
        fun present(now: Long = System.currentTimeMillis()): Boolean =
            lastSeenAt > 0L && (now - lastSeenAt) < PRESENCE_WINDOW_MS
    }

    private val drones = mutableMapOf<String, Drone>()   // label -> drone
    private val byIp = mutableMapOf<String, Drone>()     // ip -> drone

    private var cmdSock: DatagramSocket? = null
    private var stateSock: DatagramSocket? = null
    private var videoSock: DatagramSocket? = null

    private val running = AtomicBoolean(false)
    private var cmdThread: Thread? = null
    private var stateThread: Thread? = null
    private var videoThread: Thread? = null
    private var statusThread: Thread? = null
    private var lastAutoScanAt: Long = 0L

    private val handler = Handler(Looper.getMainLooper())

    /** Set by [PhoneAgentService] so the bridge can answer the host's drone commands. */
    var socketProvider: (() -> io.socket.client.Socket?)? = null

    /** Called when the owner changes the set of drones this phone carries. */
    var onDronesChanged: ((List<Drone>) -> Unit)? = null

    // ---- lifecycle ---------------------------------------------------------

    /**
     * Open the three sockets and start the loops.
     *
     * The command socket is bound to a fixed port so the drone's binding stays valid
     * across a reconnect; the state and video sockets are bound to the same fixed ports
     * the drone pushes to.
     */
    fun start() {
        if (!running.compareAndSet(false, true)) return
        try {
            cmdSock = DatagramSocket(null).apply {
                reuseAddress = true
                bind(InetSocketAddress(Protocol.DRONE_CMD_PORT))
                soTimeout = 300
            }
            stateSock = DatagramSocket(null).apply {
                reuseAddress = true
                bind(InetSocketAddress(Protocol.DRONE_STATE_PORT))
                soTimeout = 300
            }
            videoSock = DatagramSocket(null).apply {
                reuseAddress = true
                bind(InetSocketAddress(Protocol.DRONE_VIDEO_PORT))
                soTimeout = 300
            }
        } catch (e: Exception) {
            Log.e(TAG, "could not open the drone sockets", e)
            stop()
            return
        }

        cmdThread = Thread({ cmdLoop() }, "drone-cmd").also { it.isDaemon = true; it.start() }
        stateThread = Thread({ stateLoop() }, "drone-state").also { it.isDaemon = true; it.start() }
        videoThread = Thread({ videoLoop() }, "drone-video").also { it.isDaemon = true; it.start() }
        statusThread = Thread({ statusLoop() }, "drone-status").also { it.isDaemon = true; it.start() }
        Log.i(TAG, "drone bridge started")
    }

    fun stop() {
        if (!running.compareAndSet(true, false)) return
        listOf(cmdSock, stateSock, videoSock).forEach {
            try { it?.close() } catch (e: Exception) { /* already closed */ }
        }
        cmdSock = null
        stateSock = null
        videoSock = null
        Log.i(TAG, "drone bridge stopped")
    }

    // ---- the drone's Wi-Fi conversation -------------------------------------

    /**
     * Answer the host's drone command by running it on the drone.
     *
     * The answer is the drone's own text, so the host's SafetyGuard and the TelloClient
     * see exactly what they would see with the drone on the bench.
     */
    fun handleCommand(droneLabel: String, cmd: String): Pair<Boolean, String> {
        val drone = drones[droneLabel] ?: return false to "this phone does not carry a drone called $droneLabel"
        val sock = cmdSock ?: return false to "the drone link is not open"
        val verb = cmd.trim().split(' ').firstOrNull()?.lowercase() ?: ""
        return try {
            val addr = InetAddress.getByName(drone.ip)
            sock.send(DatagramPacket(cmd.toByteArray(), cmd.length, addr, Protocol.DRONE_CMD_PORT))
            // `rc` is never answered by the drone: it holds the stick values until
            // the next one. Waiting for a reply that will never come would cap the
            // joystick at one command per round trip.
            if (verb in Protocol.DRONE_NO_REPLY_COMMANDS) return true to "ok"
            // The drone answers on the socket that sent its first `command`, which is
            // this one - so the reply arrives here.
            val buffer = ByteArray(2048)
            val packet = DatagramPacket(buffer, buffer.size)
            sock.soTimeout = 3_000
            sock.receive(packet)
            sock.soTimeout = 300
            val text = String(packet.data, 0, packet.length).trim()
            true to text
        } catch (e: Exception) {
            Log.w(TAG, "drone $droneLabel did not answer '$cmd': ${e.message}")
            false to "error"
        }
    }

    private fun cmdLoop() {
        val buffer = ByteArray(2048)
        while (running.get()) {
            val sock = cmdSock ?: continue
            try {
                val packet = DatagramPacket(buffer, buffer.size)
                sock.receive(packet)
                val text = String(packet.data, 0, packet.length).trim()
                Log.i(TAG, "command from the drone: $text")
            } catch (e: Exception) {
                // A timeout is the normal case; the loop only exists to keep the socket
                // readable and to notice a drone that talks back on its own.
            }
        }
    }

    private fun stateLoop() {
        val buffer = ByteArray(4096)
        while (running.get()) {
            val sock = stateSock ?: continue
            try {
                val packet = DatagramPacket(buffer, buffer.size)
                sock.receive(packet)
                val drone = byIp[packet.address?.hostAddress]
                if (drone == null) continue
                drone.lastSeenAt = System.currentTimeMillis()
                val text = String(packet.data, 0, packet.length).trim()
                emit(Protocol.EV_DRONE_STATE, JSONObject().put("drone", drone.label).put("text", text))
            } catch (e: Exception) {
                // timeout
            }
        }
    }

    private fun videoLoop() {
        val buffer = ByteArray(65535)
        while (running.get()) {
            val sock = videoSock ?: continue
            try {
                val packet = DatagramPacket(buffer, buffer.size)
                sock.receive(packet)
                val drone = byIp[packet.address?.hostAddress]
                if (drone == null) continue
                drone.lastSeenAt = System.currentTimeMillis()
                val bytes = packet.data.copyOf(packet.length)
                // The host injects the packet on the port ffmpeg reads, so the whole
                // existing video pipeline works unchanged.
                emitBinary(Protocol.EV_DRONE_VIDEO, JSONObject().put("drone", drone.label), bytes)
            } catch (e: Exception) {
                // timeout
            }
        }
    }

    private fun statusLoop() {
        while (running.get()) {
            try {
                Thread.sleep(STATUS_INTERVAL_MS)
            } catch (e: InterruptedException) {
                return
            }
            if (!running.get()) return
            reportStatus()
            maybeAutoScan()
        }
    }

    /**
     * Look for a drone when there is a reason to believe one is there.
     *
     * The scan is the expensive part (it walks the hotspot's subnet), so it only
     * runs when the hotspot is on and no drone is known yet, and at most once a
     * minute.
     */
    private fun maybeAutoScan() {
        if (!running.get()) return
        if (drones.isNotEmpty()) return
        if (!hotspotEnabled()) return
        val now = System.currentTimeMillis()
        if (now - lastAutoScanAt < AUTO_SCAN_INTERVAL_MS) return
        lastAutoScanAt = now
        Log.i(TAG, "hotspot is on and no drone is known yet - scanning")
        Thread({ discover() }, "drone-autoscan").also { it.isDaemon = true; it.start() }
    }

    // ---- discovering the drones --------------------------------------------

    /**
     * Find the drones on the hotspot's subnet.
     *
     * The scan sends `command` - the SDK handshake - to every address of the subnet and
     * keeps the ones that answer. It MUST use the permanent command socket: a drone
     * binds to the address:port that sent its first `command`, so a scan from another
     * port would leave every drone answering a socket that no longer exists.
     */
    fun discover(): List<Drone> {
        val sock = cmdSock ?: return emptyList()
        val found = mutableListOf<Drone>()
        val subnet = hotspotSubnetPrefix() ?: run {
            Log.w(TAG, "no hotspot interface found - is the hotspot on?")
            return emptyList()
        }
        val buffer = ByteArray(2048)
        for (host in 2..254) {
            val ip = "$subnet$host"
            try {
                val addr = InetAddress.getByName(ip)
                sock.soTimeout = DISCOVERY_TIMEOUT_MS
                sock.send(DatagramPacket("command".toByteArray(), 7, addr, Protocol.DRONE_CMD_PORT))
                val packet = DatagramPacket(buffer, buffer.size)
                sock.receive(packet)
                val reply = String(packet.data, 0, packet.length).trim()
                if (reply.isNotEmpty() && !reply.equals("error", ignoreCase = true)) {
                    // A drone the owner already named keeps its name: the label is
                    // what the host's configuration names, so losing it would lose
                    // the drone.
                    val known = byIp[ip]
                    val drone = known ?: Drone("drone${found.size + 1}", ip)
                    found.add(drone)
                    Log.i(TAG, "found a drone at $ip (answered '$reply') as ${drone.label}")
                }
            } catch (e: Exception) {
                // Not a drone, or not there.
            }
        }
        sock.soTimeout = 300
        if (found.isNotEmpty()) {
            setDrones(found)
        }
        return found
    }

    /**
     * The subnet the hotspot hands out on, read from the phone's own address.
     *
     * The hotspot's address is the one the drone sees as its gateway, so its first three
     * octets are the subnet the leases come from.
     */
    /** The subnet the hotspot hands out on - the prefix the drones live on. */
    fun hotspotSubnet(): String? = hotspotSubnetPrefix()

    /**
     * The hotspot's own address, found two ways.
     *
     * The NAME first: Android's tethering interface is called `ap0`, `swlan0`,
     * `tether0`... on every release and vendor, and it is the only interface that IS the
     * hotspot - the phone's own Wi-Fi client is a different one. Then the well-known
     * Android hotspot subnets as a fallback.
     *
     * The name comes first on purpose: some Android builds hand out a hotspot subnet
     * outside the three well-known ones, and a phone whose hotspot is on but not
     * recognised would report "no hotspot" and never look for the drone.
     */
    private fun hotspotAddress(): String? {
        val interfaces = try {
            NetworkInterface.getNetworkInterfaces()
        } catch (e: Exception) {
            null
        } ?: return null
        val byName = mutableListOf<String>()
        val byKnownSubnet = mutableListOf<String>()
        while (interfaces?.hasMoreElements() == true) {
            val nif = interfaces.nextElement()
            val name = nif.name.lowercase()
            for (addr in nif.inetAddresses) {
                val ip = addr.hostAddress ?: continue
                if (ip.contains(':')) continue
                if (HOTSPOT_INTERFACE_NAMES.any { name.startsWith(it) }) {
                    byName.add(ip)
                }
                if (HOTSPOT_SUBNETS.any { ip.startsWith(it) }) {
                    byKnownSubnet.add(ip)
                }
            }
        }
        return byName.firstOrNull() ?: byKnownSubnet.firstOrNull()
    }

    private fun hotspotSubnetPrefix(): String? =
        hotspotAddress()?.let { ip ->
            if (ip.contains('.')) ip.substringBeforeLast('.') + "." else null
        }

    /** Whether the phone's hotspot is on - the drones cannot be reached without it. */
    fun hotspotEnabled(): Boolean = hotspotAddress() != null

    // ---- the drone list ----------------------------------------------------

    /** The drones this phone carries. */
    fun list(): List<Drone> = drones.values.toList()

    /**
     * Set the drones this phone carries.
     *
     * The labels are the owner's, and the host's configuration names them - the drones'
     * addresses come from the hotspot's DHCP and change from session to session, so
     * they cannot live in the host's configuration.
     */
    fun setDrones(newDrones: List<Drone>) {
        drones.clear()
        byIp.clear()
        newDrones.forEach {
            drones[it.label] = it
            byIp[it.ip] = it
        }
        onDronesChanged?.invoke(list())
        reportStatus()
    }

    /** Give a discovered drone the label the owner chose. */
    fun labelDrone(ip: String, label: String) {
        val existing = byIp[ip]
        if (existing != null) {
            drones.remove(existing.label)
            byIp.remove(ip)
            val renamed = Drone(label, ip)
            renamed.lastSeenAt = existing.lastSeenAt
            drones[label] = renamed
            byIp[ip] = renamed
        } else {
            val fresh = Drone(label, ip)
            drones[label] = fresh
            byIp[ip] = fresh
        }
        onDronesChanged?.invoke(list())
        reportStatus()
    }

    /**
     * Tell the host what this phone can carry right now.
     *
     * The host is the one that chooses the path (TASK-173): the drone sits on ONE Wi-Fi
     * network at a time, and the host prefers the lab's own radio and falls back to this
     * phone. So the host has to know two things: is the hotspot on, and is the drone
     * actually on it. `present` is per drone, because a hotspot with two drones on it
     * and one of them asleep is a normal Tuesday.
     */
    private fun reportStatus() {
        val list = JSONArray()
        drones.values.forEach {
            list.put(JSONObject()
                .put("label", it.label)
                .put("ip", it.ip)
                .put("present", it.present()))
        }
        emit(Protocol.EV_DRONE_STATUS, JSONObject()
            .put("drones", list)
            .put("hotspot", hotspotEnabled())
            .put("hotspot_subnet", hotspotSubnetPrefix() ?: ""))
    }

    // ---- the socket --------------------------------------------------------

    private fun emit(event: String, payload: JSONObject) {
        val socket = socketProvider?.invoke() ?: return
        if (!socket.connected()) return
        socket.emit(event, payload)
    }

    /**
     * Emit one binary packet with its metadata.
     *
     * The metadata and the bytes travel as two arguments, the same shape the frame
     * event uses (`s.emit(Protocol.EV_FRAME, meta, jpeg)`), so the host's handler
     * receives them as it does for the phone's own frames.
     */
    private fun emitBinary(event: String, meta: JSONObject, bytes: ByteArray) {
        val socket = socketProvider?.invoke() ?: return
        if (!socket.connected()) return
        socket.emit(event, meta, bytes)
    }
}
