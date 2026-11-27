package com.mockschan.cashless.scan

private const val HEX_DIGITS = "0123456789ABCDEF"
private val UID_LENGTHS = setOf(8, 14, 20)

internal fun normalizeBandUid(value: String): String? {
    if (value.length !in UID_LENGTHS || !value.all(::isHexDigit)) return null
    return value.uppercase()
}

private fun isHexDigit(character: Char): Boolean =
    character in '0'..'9' || character in 'A'..'F' || character in 'a'..'f'

internal fun ByteArray.toBandUid(allowOtherLengths: Boolean = false): String? {
    if (allowOtherLengths) {
        if (size !in 4..16) return null
    } else if (size * 2 !in UID_LENGTHS) return null
    return buildString(size * 2) {
        for (byte in this@toBandUid) {
            val unsigned = byte.toInt() and 0xff
            append(HEX_DIGITS[unsigned shr 4])
            append(HEX_DIGITS[unsigned and 0x0f])
        }
    }
}

internal class ScanDebouncer {
    private var lastUid: String? = null
    private var lastScanTime = 0L

    fun accept(uid: String, elapsedRealtimeMillis: Long): Boolean {
        if (uid == lastUid && elapsedRealtimeMillis - lastScanTime in 0 until 1_000L) {
            return false
        }
        lastUid = uid
        lastScanTime = elapsedRealtimeMillis
        return true
    }
}

internal sealed interface HidScanResult {
    data object Ignored : HidScanResult
    data object Consumed : HidScanResult
    data class Scan(val uid: String) : HidScanResult
}

internal class HidScanFrames {
    private class Frame(val startedAt: Long) {
        var lastKeyAt = startedAt
        var prefixLength = 0
        var rejected = false
        val uid = StringBuilder()
    }

    private val frames = mutableMapOf<Int, Frame>()

    fun accept(deviceId: Int, character: Char, eventTimeMillis: Long): HidScanResult {
        val previous = frames[deviceId]
        if (previous != null && eventTimeMillis - previous.lastKeyAt !in 0..MAX_KEY_GAP_MS) {
            frames.remove(deviceId)
        }

        if (character == '\n') {
            val frame = frames.remove(deviceId) ?: return HidScanResult.Ignored
            val uid = if (!frame.rejected && frame.prefixLength == PREFIX.length &&
                eventTimeMillis - frame.startedAt <= MAX_FRAME_MS
            ) {
                normalizeBandUid(frame.uid.toString())
            } else {
                null
            }
            return if (uid == null) HidScanResult.Consumed else HidScanResult.Scan(uid)
        }

        val frame = frames.getOrPut(deviceId) { Frame(eventTimeMillis) }
        frame.lastKeyAt = eventTimeMillis
        if (frame.rejected || eventTimeMillis - frame.startedAt > MAX_FRAME_MS) {
            frame.rejected = true
            return HidScanResult.Consumed
        }

        if (frame.prefixLength < PREFIX.length) {
            if (character == PREFIX[frame.prefixLength]) {
                frame.prefixLength++
                return HidScanResult.Consumed
            }
            frame.rejected = true
            return if (frame.prefixLength == 0) HidScanResult.Ignored else HidScanResult.Consumed
        }

        if (!isHexDigit(character) || frame.uid.length >= UID_LENGTHS.max()) {
            frame.rejected = true
        } else {
            frame.uid.append(character)
        }
        return HidScanResult.Consumed
    }

    fun removeDevice(deviceId: Int) {
        frames.remove(deviceId)
    }

    fun reset() {
        frames.clear()
    }

    private companion object {
        const val PREFIX = "OD"
        const val MAX_KEY_GAP_MS = 180L
        const val MAX_FRAME_MS = 1_200L
    }
}
