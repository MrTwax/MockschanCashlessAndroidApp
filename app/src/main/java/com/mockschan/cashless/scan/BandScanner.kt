package com.mockschan.cashless.scan

import android.app.Activity
import android.content.Context
import android.hardware.input.InputManager
import android.nfc.NfcAdapter
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.view.InputDevice
import android.view.KeyEvent

internal interface BandScanner {
    fun start()
    fun stop()
}

internal class ReaderModeScanner(
    private val activity: Activity,
    private val onScan: (String) -> Unit
) : BandScanner {
    private val adapter = NfcAdapter.getDefaultAdapter(activity)
    private var active = false
    private var generation = 0

    val isAvailable: Boolean get() = adapter != null
    val isEnabled: Boolean get() = adapter?.isEnabled == true

    override fun start() {
        val reader = adapter ?: return
        if (active || !reader.isEnabled) return
        val readerGeneration = ++generation
        active = true
        reader.enableReaderMode(
            activity,
            { tag ->
                val uid = tag.id?.toBandUid() ?: return@enableReaderMode
                activity.runOnUiThread {
                    if (active && readerGeneration == generation) onScan(uid)
                }
            },
            NfcAdapter.FLAG_READER_NFC_A or NfcAdapter.FLAG_READER_SKIP_NDEF_CHECK,
            null
        )
    }

    override fun stop() {
        if (!active) return
        active = false
        generation++
        adapter?.disableReaderMode(activity)
    }
}

internal class HidKeyboardScanner(
    private val onScan: (String) -> Unit
) : BandScanner {
    private val frames = HidScanFrames()
    private val consumedKeys = mutableSetOf<Pair<Int, Int>>()
    private var manager: InputManager? = null
    private var onDisconnected: (() -> Unit)? = null
    private var lastScannerDeviceId: Int? = null
    private var active = false

    private val listener = object : InputManager.InputDeviceListener {
        override fun onInputDeviceAdded(deviceId: Int) = Unit
        override fun onInputDeviceChanged(deviceId: Int) = Unit

        override fun onInputDeviceRemoved(deviceId: Int) {
            frames.removeDevice(deviceId)
            consumedKeys.removeAll { it.first == deviceId }
            if (lastScannerDeviceId == deviceId) {
                lastScannerDeviceId = null
                onDisconnected?.invoke()
            }
        }
    }

    override fun start() {
        active = true
    }

    override fun stop() {
        active = false
        reset()
        stopObserving()
    }

    fun observeConnection(context: Context, onDisconnected: () -> Unit) {
        this.onDisconnected = onDisconnected
        if (manager != null) return
        manager = (context.getSystemService(Context.INPUT_SERVICE) as? InputManager)?.also {
            it.registerInputDeviceListener(listener, Handler(Looper.getMainLooper()))
            val previousDevice = lastScannerDeviceId
            if (previousDevice != null && previousDevice !in it.inputDeviceIds) {
                listener.onInputDeviceRemoved(previousDevice)
            }
        }
    }

    fun stopObserving() {
        manager?.unregisterInputDeviceListener(listener)
        manager = null
        onDisconnected = null
    }

    fun reset() {
        frames.reset()
        consumedKeys.clear()
    }

    fun onKeyEvent(event: KeyEvent, captureEnabled: Boolean = true): Boolean {
        val key = event.deviceId to event.keyCode
        if (event.action == KeyEvent.ACTION_UP && consumedKeys.remove(key)) return true
        if (!active) return false
        val fromRecognizedScanner =
            event.deviceId == lastScannerDeviceId && event.isFromSource(InputDevice.SOURCE_KEYBOARD)
        if (!captureEnabled) return fromRecognizedScanner
        if (event.action != KeyEvent.ACTION_DOWN || event.repeatCount > 0) {
            return fromRecognizedScanner || key in consumedKeys
        }

        val device = event.device ?: return false
        if (device.isVirtual || !event.isFromSource(InputDevice.SOURCE_KEYBOARD)) return false
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q && !device.isExternal) return false
        if (KeyEvent.isModifierKey(event.keyCode)) return false

        val character = when (event.keyCode) {
            KeyEvent.KEYCODE_ENTER, KeyEvent.KEYCODE_NUMPAD_ENTER -> '\n'
            else -> event.unicodeChar.takeIf { it in 32..126 }?.toChar() ?: '\u0000'
        }
        val result = frames.accept(event.deviceId, character, event.eventTime)
        if (result == HidScanResult.Ignored && !fromRecognizedScanner) return false
        consumedKeys.add(key)
        if (result is HidScanResult.Scan) {
            lastScannerDeviceId = event.deviceId
            onScan(result.uid)
        }
        return true
    }
}
