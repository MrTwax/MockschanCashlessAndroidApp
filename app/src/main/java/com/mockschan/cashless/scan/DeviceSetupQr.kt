package com.mockschan.cashless.scan

import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import org.json.JSONException
import org.json.JSONObject
import org.json.JSONTokener

internal class DeviceSetupQr(val url: HttpUrl, val deviceKey: String)

private const val MAX_PAYLOAD_LENGTH = 4096
private const val HTTPS_PREFIX = "https://"
private val deviceKeyPattern = Regex("[A-Za-z0-9_-]{43}")

internal fun parseDeviceSetupQr(contents: String?): DeviceSetupQr? {
    if (contents.isNullOrBlank() || contents.length > MAX_PAYLOAD_LENGTH ||
        '\u0000' in contents
    ) {
        return null
    }

    val json = try {
        val tokens = JSONTokener(contents)
        val value = tokens.nextValue() as? JSONObject ?: return null
        if (tokens.nextClean() != '\u0000') return null
        value
    } catch (_: JSONException) {
        return null
    }

    if (json.opt("type") != "odentaler-device" || json.opt("version") != 1) return null
    val deviceKey = json.opt("device_key") as? String ?: return null
    if (!deviceKeyPattern.matches(deviceKey)) return null

    val rawUrl = json.opt("url") as? String ?: return null
    if (!rawUrl.startsWith(HTTPS_PREFIX, ignoreCase = true) ||
        rawUrl.getOrNull(HTTPS_PREFIX.length) == '/' || rawUrl.any { it <= ' ' || it == '\\' }
    ) {
        return null
    }
    val url = rawUrl.toHttpUrlOrNull()?.takeIf {
        it.isHttps && it.username.isEmpty() && it.password.isEmpty() &&
            it.query == null && it.fragment == null
    } ?: return null

    return DeviceSetupQr(url, deviceKey)
}
