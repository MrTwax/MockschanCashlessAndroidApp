package com.mockschan.cashless.scan

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ScanInputTest {
    @Test
    fun normalizesNfcAUidLengthsAndPreservesByteOrder() {
        assertEquals("0400ABFF", byteArrayOf(0x04, 0x00, 0xab.toByte(), 0xff.toByte()).toBandUid())
        assertEquals("040011AA223344", normalizeBandUid("040011aa223344"))
        assertEquals("0102030405060708090A", normalizeBandUid("0102030405060708090a"))
        assertNull(normalizeBandUid(" 0400ABFF"))
        assertNull(normalizeBandUid("0400ABFG"))
        assertNull(normalizeBandUid("0400AB"))
        assertNull(normalizeBandUid("0400ABFF0400ABFF"))
        assertNull(ByteArray(8).toBandUid())
    }

    @Test
    fun rejectsRepeatedScanOfSameBandAcrossSourcesUntilCooldownExpires() {
        val scans = ScanDebouncer()
        assertTrue(scans.accept("0400ABFF", 100L))
        assertFalse(scans.accept("0400ABFF", 500L))
        assertFalse(scans.accept("0400ABFF", 1_099L))
        assertTrue(scans.accept("0400ABFF", 1_100L))
        assertTrue(scans.accept("04000001", 1_101L))
    }

    @Test
    fun hidCompletesOnlyOnEnterAndNormalizesUid() {
        val frames = HidScanFrames()

        assertEquals(HidScanResult.Consumed, frames.feed("OD0400abff"))
        assertEquals(HidScanResult.Scan("0400ABFF"), frames.accept(1, '\n', 220L))
        assertEquals(HidScanResult.Ignored, frames.accept(1, '\n', 240L))
    }

    @Test
    fun hidRejectsMissingOrInvalidPrefixAndMalformedOrOversizedUid() {
        val frames = HidScanFrames()

        for (payload in listOf("0400ABFF", "XOD0400ABFF", "OX0400ABFF", "OD0400!ABFF",
            "OD0400ABF", "OD" + "A".repeat(21))) {
            assertEquals(HidScanResult.Consumed, frames.feed(payload + "\n"))
        }
        assertEquals(HidScanResult.Scan("0400ABFF"), frames.feed("OD0400ABFF\n"))
    }

    @Test
    fun hidAcceptsOnlyFastAndBoundedFrames() {
        val frames = HidScanFrames()
        frames.feed("OD0400ABFF")
        assertEquals(HidScanResult.Ignored, frames.accept(1, '\n', 1_000L))
        assertEquals(HidScanResult.Consumed,
            frames.feed("OD0400ABFF\n", keyGap = 150L))
        assertEquals(HidScanResult.Scan("0400ABFF"), frames.feed("OD0400ABFF\n"))
    }

    @Test
    fun hidNeverCombinesDevicesAndDropsPartialFramesOnDisconnectOrFocusLoss() {
        val frames = HidScanFrames()

        frames.feed("OD0400", deviceId = 1)
        assertEquals(HidScanResult.Consumed, frames.feed("ABFF\n", deviceId = 2))
        assertEquals(HidScanResult.Scan("0400ABFF"), frames.feed("ABFF\n", deviceId = 1, start = 130L))

        frames.feed("OD0400")
        frames.removeDevice(1)
        assertEquals(HidScanResult.Consumed, frames.feed("ABFF\n", start = 130L))

        frames.feed("OD0400")
        frames.reset()
        assertEquals(HidScanResult.Consumed, frames.feed("ABFF\n", start = 130L))
    }

    private fun HidScanFrames.feed(
        keys: String,
        deviceId: Int = 1,
        start: Long = 10L,
        keyGap: Long = 20L
    ): HidScanResult =
        keys.foldIndexed(HidScanResult.Ignored as HidScanResult) { index, _, key ->
            accept(deviceId, key, start + index * keyGap)
        }
}
