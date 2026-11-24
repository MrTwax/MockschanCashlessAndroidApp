package com.mockschan.cashless

import okhttp3.Call
import okhttp3.Callback
import okhttp3.HttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import javax.net.ssl.SSLException

internal enum class ConnectionFailure { DNS, TLS, TIMEOUT, NETWORK }

internal data class ApiReply(
    val status: Int,
    val body: String?,
    val connectionFailure: ConnectionFailure? = null
) {
    fun objectBody(): JSONObject? = runCatching { JSONObject(body ?: return null) }.getOrNull()
    fun arrayBody(): JSONArray? = runCatching { JSONArray(body ?: return null) }.getOrNull()
    val successful: Boolean get() = status in 200..299
    val error: String? get() = objectBody()?.optString("error")?.takeIf(String::isNotEmpty)

    fun setupIssue(): String = when (connectionFailure) {
        ConnectionFailure.DNS -> "Die Serveradresse wurde nicht gefunden. Prüfe die Adresse und das WLAN."
        ConnectionFailure.TLS -> "Das HTTPS-Zertifikat des Servers konnte nicht geprüft werden. Prüfe Servername und Zertifikat."
        ConnectionFailure.TIMEOUT -> "Der Server antwortet zu langsam. Prüfe das WLAN und ob der Server läuft."
        ConnectionFailure.NETWORK -> "Der Server ist nicht erreichbar. Prüfe das WLAN und ob der Server läuft."
        null -> when (status) {
            401, 403 -> "Der Server hat den Gerätecode abgelehnt. Verwende einen für dieses Gerät registrierten Code."
            404, 405 -> "Unter dieser Adresse fehlt die Odentaler-Schnittstelle /v1. Prüfe die Serveradresse und die Backend-Version."
            in 300..399 -> "Die Serveradresse leitet weiter. Gib die endgültige HTTPS-Adresse ein."
            in 500..599 -> "Der Server antwortet, kann die Veranstaltung aber gerade nicht laden. Bitte prüfe das Backend."
            else -> "Die Serverantwort passt nicht zur App. Prüfe die Backend-Version."
        }
    }

    companion object {
        fun networkError(error: IOException): ApiReply = ApiReply(0, null, when (error) {
            is UnknownHostException -> ConnectionFailure.DNS
            is SSLException -> ConnectionFailure.TLS
            is SocketTimeoutException -> ConnectionFailure.TIMEOUT
            else -> ConnectionFailure.NETWORK
        })
    }
}

internal class OdentalerApi(private val base: HttpUrl, private val deviceKey: String) {
    fun request(
        path: String,
        method: String = "GET",
        payload: String? = null,
        token: String? = null,
        bookingKey: String? = null,
        query: Map<String, String> = emptyMap(),
        complete: (ApiReply) -> Unit
    ) {
        val url = base.newBuilder().addPathSegments("v1/$path").apply {
            query.forEach { (name, value) -> addQueryParameter(name, value) }
        }.build()
        val body = payload?.toRequestBody("application/json".toMediaType())
        val request = Request.Builder().url(url).method(method, body).apply {
            if (token == null) header("X-Device-Key", deviceKey)
            else header("Authorization", "Bearer $token")
            if (bookingKey != null) header("Idempotency-Key", bookingKey)
        }.build()

        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) = complete(ApiReply.networkError(e))

            override fun onResponse(call: Call, response: Response) {
                val reply = response.use {
                    try {
                        ApiReply(it.code, it.body?.string())
                    } catch (error: IOException) {
                        ApiReply.networkError(error)
                    }
                }
                complete(reply)
            }
        })
    }

    companion object {
        private val client = OkHttpClient.Builder()
            .retryOnConnectionFailure(false)
            .followRedirects(false)
            .followSslRedirects(false)
            .build()
    }
}
