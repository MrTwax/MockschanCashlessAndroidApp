package com.mockschan.cashless

import android.content.SharedPreferences
import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.annotation.RequiresApi
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

internal class DeviceKeyStore(private val preferences: SharedPreferences) {
    fun read(): String? {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return null
        val stored = preferences.getString(PREF, null) ?: return null
        return runCatching {
            val parts = stored.split(".")
            val iv = Base64.decode(parts[0], Base64.NO_WRAP)
            val encrypted = Base64.decode(parts[1], Base64.NO_WRAP)
            val cipher = Cipher.getInstance(CIPHER)
            cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, iv))
            cipher.doFinal(encrypted).toString(Charsets.UTF_8)
        }.getOrNull()
    }

    fun save(value: String, editor: SharedPreferences.Editor): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return false
        return runCatching {
            val cipher = Cipher.getInstance(CIPHER)
            cipher.init(Cipher.ENCRYPT_MODE, key())
            val iv = Base64.encodeToString(cipher.iv, Base64.NO_WRAP)
            val encrypted = Base64.encodeToString(cipher.doFinal(value.toByteArray()), Base64.NO_WRAP)
            editor.putString(PREF, "$iv.$encrypted").remove("apiKey").commit()
        }.getOrDefault(false)
    }

    fun clear(editor: SharedPreferences.Editor): Boolean = editor.remove(PREF).remove("apiKey").commit()

    @RequiresApi(Build.VERSION_CODES.M)
    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        val existing = store.getKey(ALIAS, null)
        if (existing is SecretKey) return existing
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(
                KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                    .build()
            )
        }.generateKey()
    }

    private companion object {
        const val PREF = "encryptedDeviceKey"
        const val ALIAS = "odentaler-device-key"
        const val CIPHER = "AES/GCM/NoPadding"
    }
}
