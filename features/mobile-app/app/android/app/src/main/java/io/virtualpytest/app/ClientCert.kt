package io.virtualpytest.app

import android.content.Context
import android.net.Uri
import android.security.KeyChain
import android.util.Log
import android.webkit.WebView
import okhttp3.OkHttpClient
import java.net.Socket
import java.net.URLConnection
import java.security.KeyStore
import java.security.Principal
import java.security.PrivateKey
import java.security.cert.X509Certificate
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLEngine
import javax.net.ssl.SSLSocketFactory
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509ExtendedKeyManager
import javax.net.ssl.X509TrustManager

/**
 * The owner's Cloudflare client certificate (mTLS), so the app gets past the WAF IP whitelist
 * from any network (4G, hotel…) — see docs/agent/infra/CLOUDFLARE.md, "WAF whitelist and
 * owner-device certificates".
 *
 * The certificate is installed in Android's KeyChain ("VPN & app user certificate"), never in
 * the APK. The user grants this app one alias once, through Android's own picker (the WebView's
 * first client-certificate request, see MainActivity); only that alias name is stored here. The
 * key itself is read from KeyChain on every handshake and never kept anywhere else.
 *
 * Only the deployment's own hosts (server, slave servers, Supabase, the host's public URL, the
 * APK download) get the certificate. LAN hosts (host_api_url) connect exactly as before, and a
 * server that does not ask for a certificate never sees one.
 */
object ClientCert {
    private const val TAG = "VptClientCert"
    private const val KEY_ALIAS = "client_cert_alias"

    @Volatile private var cached: Pair<String, SSLContext>? = null

    fun alias(context: Context): String? =
        PhoneAgentPrefs.getString(context, KEY_ALIAS)?.takeIf { it.isNotBlank() }

    fun setAlias(context: Context, alias: String) {
        PhoneAgentPrefs.put(context, KEY_ALIAS, alias)
    }

    /**
     * Forget the alias (declined, removed or revoked) so Android's picker shows again on the
     * next request. The WebView remembers a proceed/ignore per host for the whole process, so
     * that memory is dropped too.
     */
    fun clear(context: Context) {
        if (alias(context) == null) return
        Log.i(TAG, "client certificate alias cleared")
        PhoneAgentPrefs.put(context, KEY_ALIAS, null)
        cached = null
        android.os.Handler(android.os.Looper.getMainLooper()).post { WebView.clearClientCertPreferences(null) }
    }

    /** True for a host of the configured deployment — the only hosts that get the certificate. */
    fun isCertHost(context: Context, host: String?): Boolean {
        if (host.isNullOrBlank()) return false
        return deploymentHosts(context).any { it.equals(host, ignoreCase = true) }
    }

    private fun deploymentHosts(context: Context): Set<String> {
        val urls = listOf(
            PhoneAgentPrefs.KEY_SERVER_URL,
            PhoneAgentPrefs.KEY_SUPABASE_URL,
            PhoneAgentPrefs.KEY_HOST_URL,
        ).mapNotNull { PhoneAgentPrefs.getString(context, it) } +
            PhoneAgentPrefs.getString(context, PhoneAgentPrefs.KEY_SLAVE_SERVER_URL).orEmpty().split(',') +
            BuildConfig.APK_URL
        return urls.mapNotNull { it.trim().takeIf(String::isNotEmpty)?.let(Uri::parse)?.host }.toSet()
    }

    /** Key and chain for `alias`, straight from KeyChain; null (and the alias cleared) when gone. Blocking. */
    fun load(context: Context, alias: String): Pair<PrivateKey, Array<X509Certificate>>? {
        return try {
            val key = KeyChain.getPrivateKey(context, alias)
            val chain = KeyChain.getCertificateChain(context, alias)
            if (key == null || chain.isNullOrEmpty()) {
                clear(context)
                null
            } else {
                key to chain
            }
        } catch (e: Exception) {
            Log.w(TAG, "client certificate '$alias' unavailable: ${e.message}")
            clear(context)
            null
        }
    }

    /** Give an HTTPS connection to a deployment host the certificate, when one is granted. */
    fun applyTo(context: Context, conn: URLConnection) {
        if (conn !is HttpsURLConnection || !isCertHost(context, conn.url.host)) return
        sslContext(context)?.let { conn.sslSocketFactory = it.socketFactory }
    }

    /**
     * An OkHttp client presenting the certificate (Socket.IO's transport), or null when no
     * alias is granted — the caller then keeps the library's default client.
     */
    fun okHttpClient(context: Context): OkHttpClient? {
        val ssl = sslContext(context) ?: return null
        return OkHttpClient.Builder().sslSocketFactory(ssl.socketFactory, defaultTrustManager()).build()
    }

    private fun sslContext(context: Context): SSLContext? {
        val alias = alias(context) ?: return null
        cached?.let { (a, ctx) -> if (a == alias) return ctx }
        val ctx = SSLContext.getInstance("TLS")
        ctx.init(arrayOf(KeyChainKeyManager(context.applicationContext, alias)), arrayOf(defaultTrustManager()), null)
        cached = alias to ctx
        return ctx
    }

    private fun defaultTrustManager(): X509TrustManager {
        val factory = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm())
        factory.init(null as KeyStore?)
        return factory.trustManagers.filterIsInstance<X509TrustManager>().first()
    }

    /** Always offers the one granted alias; the key and chain come from KeyChain per handshake. */
    private class KeyChainKeyManager(private val context: Context, private val alias: String) : X509ExtendedKeyManager() {
        override fun chooseClientAlias(keyType: Array<out String>?, issuers: Array<out Principal>?, socket: Socket?) = alias
        override fun chooseEngineClientAlias(keyType: Array<out String>?, issuers: Array<out Principal>?, engine: SSLEngine?) = alias
        override fun getCertificateChain(alias: String?): Array<X509Certificate>? = load(context, this.alias)?.second
        override fun getPrivateKey(alias: String?): PrivateKey? = load(context, this.alias)?.first
        override fun getClientAliases(keyType: String?, issuers: Array<out Principal>?) = arrayOf(alias)
        override fun getServerAliases(keyType: String?, issuers: Array<out Principal>?): Array<String>? = null
        override fun chooseServerAlias(keyType: String?, issuers: Array<out Principal>?, socket: Socket?): String? = null
    }
}
