package com.mockschan.cashless.scan

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

class DeviceSetupQrTest {
    @Test
    fun acceptsDeviceProvisioningPayloadAndKeepsBasePath() {
        val parsed = parseDeviceSetupQr(payload(url = "https://cashless.example:8443/verein"))
        assertNotNull(parsed)
        assertEquals("https://cashless.example:8443/verein", parsed?.url.toString())
        assertEquals(DEVICE_KEY, parsed?.deviceKey)
    }

    @Test
    fun rejectsOtherQrTypesAndVersions() {
        assertNull(parseDeviceSetupQr(payload(type = "odentaler-bracelet")))
        assertNull(parseDeviceSetupQr(payload(version = 2)))
        assertNull(parseDeviceSetupQr(payload(version = "1")))
        val fractionalVersion = payload().replace("\"version\":1", "\"version\":1.0")
        assertNull(parseDeviceSetupQr(fractionalVersion))
    }

    @Test
    fun rejectsBadKeysAndMissingFields() {
        assertNull(parseDeviceSetupQr(payload(key = "abc")))
        assertNull(parseDeviceSetupQr(payload(key = DEVICE_KEY + "=")))
        assertNull(parseDeviceSetupQr(payload(key = DEVICE_KEY.dropLast(1) + ".")))
        assertNull(parseDeviceSetupQr(payload(key = 123)))
        val noKey = JSONObject(payload()).apply { remove("device_key") }
        assertNull(parseDeviceSetupQr(noKey.toString()))
    }

    @Test
    fun rejectsUnsafeAddresses() {
        val addresses = listOf(
            "http://cashless.example",
            "cashless.example",
            "https:///cashless.example",
            "https://name:password@cashless.example",
            "https://cashless.example?param=1",
            "https://cashless.example#anchor",
            "https://cashless.example\\other",
            "https://cashless.example\nother",
            " https://cashless.example"
        )
        addresses.forEach { url -> assertNull(parseDeviceSetupQr(payload(url = url))) }
    }

    @Test
    fun rejectsInvalidTrailingOrOverlongPayloads() {
        assertNull(parseDeviceSetupQr(null))
        assertNull(parseDeviceSetupQr("https://cashless.example"))
        assertNull(parseDeviceSetupQr("[]"))
        assertNull(parseDeviceSetupQr(payload() + " {}"))
        assertNull(parseDeviceSetupQr(payload() + "\u0000"))
        assertNull(parseDeviceSetupQr(payload() + " ".repeat(4096)))
    }

    private fun payload(
        type: String = "odentaler-device",
        version: Any = 1,
        url: String = "https://cashless.example",
        key: Any = DEVICE_KEY
    ): String = JSONObject()
        .put("type", type)
        .put("version", version)
        .put("url", url)
        .put("device_key", key)
        .toString()

    private companion object {
        val DEVICE_KEY = "Ab_z-".repeat(8) + "XyZ"
    }
}
