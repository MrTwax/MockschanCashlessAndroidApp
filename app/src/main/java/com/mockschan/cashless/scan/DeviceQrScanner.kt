package com.mockschan.cashless.scan

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.view.WindowManager
import com.google.zxing.client.android.Intents.Scan
import com.journeyapps.barcodescanner.CaptureActivity
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import com.mockschan.cashless.R

internal object DeviceQrScanner {
    const val REQUEST_CODE = 0x0D01
    private val contract = ScanContract()

    @Suppress("DEPRECATION")
    fun start(activity: Activity): Boolean {
        if (!activity.packageManager.hasSystemFeature(PackageManager.FEATURE_CAMERA_ANY)) return false
        val options = ScanOptions().apply {
            setCaptureActivity(DeviceQrCaptureActivity::class.java)
            setDesiredBarcodeFormats(ScanOptions.QR_CODE)
            setPrompt(activity.getString(R.string.operation_qr_prompt))
            setOrientationLocked(false)
            setBeepEnabled(false)
            setBarcodeImageEnabled(false)
            addExtra(Scan.SHOW_MISSING_CAMERA_PERMISSION_DIALOG, true)
            addExtra(
                Scan.MISSING_CAMERA_PERMISSION_DIALOG_MESSAGE,
                activity.getString(R.string.operation_qr_camera_permission)
            )
        }
        return try {
            activity.startActivityForResult(contract.createIntent(activity, options), REQUEST_CODE)
            true
        } catch (_: ActivityNotFoundException) {
            false
        }
    }

    fun read(resultCode: Int, data: Intent?): DeviceSetupQr? {
        if (resultCode != Activity.RESULT_OK || data == null) return null
        val result = contract.parseResult(resultCode, data)
        if (result.formatName != ScanOptions.QR_CODE) return null
        return parseDeviceSetupQr(result.contents)
    }
}

class DeviceQrCaptureActivity : CaptureActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        super.onCreate(savedInstanceState)
    }
}
