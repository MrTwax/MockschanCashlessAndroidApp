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

internal data class ApiReply(val status: Int, val body: String?) {
    fun objectBody(): JSONObject? = runCatching { JSONObject(body ?: return null) }.getOrNull()
    fun arrayBody(): JSONArray? = runCatching { JSONArray(body ?: return null) }.getOrNull()
    val successful: Boolean get() = status in 200..299
    val error: String? get() = objectBody()?.optString("error")?.takeIf(String::isNotEmpty)
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
            override fun onFailure(call: Call, e: IOException) = complete(ApiReply(0, null))

            override fun onResponse(call: Call, response: Response) {
                val reply = response.use {
                    try {
                        ApiReply(it.code, it.body?.string())
                    } catch (_: IOException) {
                        ApiReply(0, null)
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
