package com.mockschan.cashless

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.SharedPreferences
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.text.InputType
import android.text.method.DigitsKeyListener
import android.view.KeyEvent
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.Switch
import android.widget.TextView
import android.widget.Toast
import androidx.core.view.isVisible
import com.mockschan.cashless.scan.DeviceQrScanner
import com.mockschan.cashless.scan.HidKeyboardScanner
import com.mockschan.cashless.scan.ReaderModeScanner
import com.mockschan.cashless.scan.ScanDebouncer
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

class MainActivity : Activity() {
    private data class EventConfig(
        val id: String,
        val name: String,
        val areas: Set<String>,
        val timeoutMillis: Long,
        val presetCents: List<Long>
    )

    private data class AreaSession(val eventId: String, val area: String, val token: String)
    private data class Scan(val id: String, val balanceCents: Long, val deadline: Long)
    private data class Product(val id: Int, val name: String, val priceCents: Long, val category: String)

    private data class RetainedSale(
        val event: EventConfig,
        val session: AreaSession,
        val scan: Scan?,
        val products: List<Product>,
        val cart: Map<Int, Int>,
        val catalogLoading: Boolean
    )

    private lateinit var settings: SharedPreferences
    private lateinit var keyStore: DeviceKeyStore
    private lateinit var bookings: BookingGuard
    private lateinit var mainContent: FrameLayout
    private lateinit var nfc: ReaderModeScanner
    private lateinit var hid: HidKeyboardScanner

    private val mainHandler = Handler(Looper.getMainLooper())
    private val scanDebouncer = ScanDebouncer()
    private var eventConfig: EventConfig? = null
    private var areaSession: AreaSession? = null
    private var scan: Scan? = null
    private var scanLoading = false
    private var products: List<Product> = emptyList()
    private val cart = mutableMapOf<Int, Int>()
    private var scanGeneration = 0L
    private var screenGeneration = 0L
    private var scanExpiry: Runnable? = null
    private var messageExpiry: Runnable? = null
    private var dialog: AlertDialog? = null
    private var active = false
    private var requestRunning = false
    private var unusablePending = false
    private var csvForExport: String? = null
    private var receiveDeviceQr: ((HttpUrl, String) -> Unit)? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        mainContent = findViewById(R.id.mainContent)
        settings = getSharedPreferences("settings", MODE_PRIVATE)
        keyStore = DeviceKeyStore(settings)
        settings.edit().remove("apiKey").apply()
        val saved = settings.getString(PENDING_PREF, null)
        val pending = saved?.let { runCatching { decodePending(JSONObject(it)) }.getOrNull() }
        unusablePending = saved != null && pending == null
        bookings = BookingGuard(object : BookingStore {
            override fun read(): PendingBooking? = settings.getString(PENDING_PREF, null)?.let {
                runCatching { decodePending(JSONObject(it)) }.getOrNull()
            }

            override fun save(booking: PendingBooking?): Boolean {
                val previous = settings.getString(PENDING_PREF, null)
                val editor = settings.edit().putString(PENDING_PREF, booking?.let(::encodePending))
                if (editor.commit()) return true
                settings.edit().putString(PENDING_PREF, previous).apply()
                return false
            }
        })
        nfc = ReaderModeScanner(this, ::acceptScan)
        hid = HidKeyboardScanner(::acceptScan)
        @Suppress("DEPRECATION")
        val retained = lastNonConfigurationInstance as? RetainedSale
        if (retained == null) {
            showHome()
            if (savedInstanceState?.getBoolean(HAD_SCAN_STATE) == true && bookings.pending == null) {
                notifyUser("Der Scan wurde durch einen Neustart beendet. Bitte das Armband erneut scannen.")
            }
        } else restoreSale(retained)
    }

    @Deprecated("Android Activity configuration retention")
    override fun onRetainNonConfigurationInstance(): Any? {
        val event = eventConfig ?: return null
        val session = areaSession?.takeIf { it.area != ADMIN } ?: return null
        return RetainedSale(event, session, scan, products, cart.toMap(), scanLoading)
    }

    override fun onSaveInstanceState(outState: Bundle) {
        outState.putBoolean(HAD_SCAN_STATE, scan != null || scanLoading)
        super.onSaveInstanceState(outState)
    }

    private fun restoreSale(retained: RetainedSale) {
        eventConfig = retained.event
        areaSession = retained.session
        if (retained.session.area == CASH) showCash() else showCounter(retained.session.area)
        val band = retained.scan
        val api = api()
        if (bookings.pending != null || band == null || api == null) return
        if (SystemClock.elapsedRealtime() >= band.deadline) {
            showMessage("Die Scanzeit ist abgelaufen. Bitte das Armband erneut scannen.")
            return
        }
        scan = band
        scheduleExpiry(retained.event.timeoutMillis)
        products = retained.products
        cart.putAll(retained.cart)
        if (retained.catalogLoading && retained.session.area != CASH) {
            loadProducts(api, retained.session, screenGeneration, scanGeneration)
        } else renderSalesState()
    }

    override fun onResume() {
        super.onResume()
        active = true
        startScanner()
        renderSalesState()
        if (!requestRunning) showPending()
    }

    override fun onPause() {
        active = false
        nfc.stop()
        hid.stop()
        super.onPause()
    }

    override fun onDestroy() {
        dialog?.dismiss()
        mainHandler.removeCallbacksAndMessages(null)
        super.onDestroy()
    }

    @Deprecated("Android Activity result callback")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == DeviceQrScanner.REQUEST_CODE) {
            val receive = receiveDeviceQr
            receiveDeviceQr = null
            if (resultCode != RESULT_OK) return
            val qr = DeviceQrScanner.read(resultCode, data)
            when {
                qr == null -> notifyUser("Dieser QR-Code enthält keine gültige Serveradresse und keinen gültigen Gerätecode.")
                receive == null -> notifyUser("Bitte die Servereinrichtung öffnen und den QR-Code erneut scannen.")
                else -> receive(qr.url, qr.deviceKey)
            }
            return
        }
        if (requestCode != SAVE_CSV_REQUEST) return
        val csv = csvForExport
        csvForExport = null
        val uri = data?.data
        if (resultCode != RESULT_OK || uri == null) return
        if (csv == null) {
            notifyUser("Bitte den Export erneut in der Abrechnung starten.")
            return
        }
        val resolver = contentResolver
        Thread {
            val success = runCatching {
                checkNotNull(resolver.openOutputStream(uri)).bufferedWriter(Charsets.UTF_8).use { it.write(csv) }
            }.isSuccess
            runOnUiThread {
                if (!isDestroyed) notifyUser(if (success) "CSV gespeichert." else "CSV konnte nicht gespeichert werden.")
            }
        }.start()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (!hasFocus && ::hid.isInitialized) hid.reset()
    }

    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        if (::hid.isInitialized && isHidEnabled() && hid.onKeyEvent(event, canScan())) return true
        return super.dispatchKeyEvent(event)
    }

    @Deprecated("Android Activity back callback")
    override fun onBackPressed() {
        if (mainContent.findViewById<View?>(R.id.homeRoot) != null && !requestRunning) {
            super.onBackPressed()
        } else {
            leaveScreen()
        }
    }

    private fun installLayout(layout: Int): View {
        screenGeneration++
        receiveDeviceQr = null
        clearScan()
        clearMessage()
        mainContent.removeAllViews()
        return layoutInflater.inflate(layout, mainContent, false).also {
            mainContent.addView(it)
            clearMessage()
        }
    }

    private fun showHome(verifiedConfig: EventConfig? = null) {
        areaSession = null
        val view = installLayout(R.layout.view_home)
        val cash = view.findViewById<Button>(R.id.btnKasse)
        val drinks = view.findViewById<Button>(R.id.btnHomeDrinks)
        val food = view.findViewById<Button>(R.id.btnHomeFood)
        val wine = view.findViewById<Button>(R.id.btnHomeWine)
        val mobile = view.findViewById<Button>(R.id.btnHomeMobile)
        val admin = view.findViewById<Button>(R.id.btnAdmin)
        val settingsButton = view.findViewById<Button>(R.id.btnManualUid)
        val status = view.findViewById<TextView>(R.id.statusCard)
        view.findViewById<Button>(R.id.btnTheke).isVisible = false
        val buttons = mapOf(CASH to cash, "drinks" to drinks, "food" to food, "wine" to wine, "mobile" to mobile, ADMIN to admin)

        for ((area, button) in buttons) {
            button.isVisible = false
            button.setOnClickListener { enterArea(area) }
        }

        fun renderConfig() {
            buttons.forEach { (area, button) -> button.isVisible = area in eventConfig?.areas.orEmpty() }
            status.text = when {
                unusablePending -> "Der gespeicherte Buchungsstatus ist unlesbar. Bitte die Administration hinzuziehen."
                bookings.pending != null -> "Eine Buchung ist offen. Bitte den ursprünglichen Verkaufsbereich öffnen."
                eventConfig?.areas?.isEmpty() == true -> "Verbunden mit ${eventConfig?.name}. Für dieses Gerät sind keine Bereiche freigegeben."
                else -> eventConfig?.name.orEmpty()
            }
        }

        eventConfig = verifiedConfig
        renderConfig()
        settingsButton.text = getString(R.string.operation_setup)
        settingsButton.isVisible = bookings.pending == null && !unusablePending
        settingsButton.setOnClickListener { showConnectionSettings() }
        if (verifiedConfig != null) {
            settingsButton.isVisible = verifiedConfig.areas.isEmpty() && bookings.pending == null && !unusablePending
            return
        }
        val api = api()
        if (api == null) {
            if (bookings.pending == null && !unusablePending) status.text = "Bitte zuerst den Server einrichten."
            return
        }

        status.text = "Veranstaltung wird geladen …"
        val screen = screenGeneration
        api.request("bootstrap") { reply ->
            onScreen(screen) {
                eventConfig = if (reply.successful) decodeEvent(reply.objectBody()) else null
                if (eventConfig == null) {
                    status.text = reply.setupIssue()
                } else {
                    renderConfig()
                    settingsButton.isVisible = eventConfig?.areas.isNullOrEmpty() && bookings.pending == null && !unusablePending
                }
            }
        }
    }

    private fun enterArea(area: String) {
        val config = eventConfig ?: return
        if (requestRunning || area !in config.areas) return
        if (unusablePending && area != ADMIN) {
            notifyUser("Der gespeicherte Buchungsstatus muss geprüft werden.")
            return
        }
        val pending = bookings.pending
        if (pending != null && (pending.eventId != config.id || pending.area != area) && area != ADMIN) {
            notifyUser("Bitte zuerst die offene Buchung im ursprünglichen Bereich prüfen.")
            return
        }
        if (area == CASH || area == ADMIN) {
            val pin = EditText(this).apply {
                inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_VARIATION_PASSWORD
                setSingleLine()
            }
            trackDialog(AlertDialog.Builder(this)
                .setTitle(if (area == CASH) "Kassen-PIN" else "Admin-PIN")
                .setView(pin)
                .setNegativeButton("Abbrechen", null)
                .setPositiveButton("Öffnen") { _, _ -> openSession(config, area, pin.text.toString()) }
                .create())
        } else openSession(config, area)
    }

    private fun openSession(config: EventConfig, area: String, pin: String? = null) {
        val api = api() ?: return
        val screen = screenGeneration
        val payload = JSONObject().put("area", area).apply { if (pin != null) put("pin", pin) }
        requestRunning = true
        api.request("session", "POST", payload.toString()) { reply ->
            onScreen(screen) {
                requestRunning = false
                val token = reply.objectBody()?.optString("token")?.takeIf(String::isNotBlank)
                if (!reply.successful || token == null) {
                    notifyUser(when (reply.error) {
                        "invalid_pin" -> "Die PIN stimmt nicht."
                        "pin_locked" -> "Zu viele Versuche. Bitte kurz warten."
                        "area_unavailable" -> "Dieser Bereich ist gesperrt."
                        else -> reply.setupIssue()
                    })
                    return@onScreen
                }
                areaSession = AreaSession(config.id, area, token)
                when (area) {
                    CASH -> showCash()
                    ADMIN -> showConnectionSettings(admin = true)
                    else -> showCounter(area)
                }
                if (bookings.pending?.area == area) showPending()
            }
        }
    }

    private fun showConnectionSettings(admin: Boolean = false) {
        val page = installLayout(R.layout.view_admin)
        page.findViewById<TextView>(R.id.adminTitle).text = if (admin) "Administration" else getString(R.string.operation_setup)
        page.findViewById<View>(R.id.wineSwitchRow).isVisible = admin
        page.findViewById<View>(R.id.adminTabs).isVisible = false
        if (admin) renderAdminAreas(page)
        page.findViewById<Button>(R.id.btnBackAdmin).setOnClickListener { showHome() }
        val container = page.findViewById<FrameLayout>(R.id.adminContent)
        val view = layoutInflater.inflate(R.layout.view_admin_settings, container, false)
        container.addView(view)
        if (admin) configureAdminTabs(page, container, view)
        val address = view.findViewById<EditText>(R.id.edtBaseUrl)
        val code = view.findViewById<EditText>(R.id.edtApiKey).apply { isSaveEnabled = false }
        val useHid = view.findViewById<Switch>(R.id.switchHidScanner)
        address.setText(settings.getString(BASE_PREF, DEFAULT_BASE))
        code.hint = if (keyStore.read() == null) "Registrierungscode eingeben" else "Zum Ändern neuen Gerätecode eingeben"
        useHid.isChecked = isHidEnabled()
        val savable = bookings.pending == null && !unusablePending
        val feedback = view.findViewById<TextView>(R.id.serverSetupStatus)
        val reset = view.findViewById<Button>(R.id.btnResetBaseUrl)
        val scanQr = view.findViewById<Button>(R.id.btnScanDeviceQr)
        var qrBase: HttpUrl? = null
        var qrKey: String? = null
        scanQr.isEnabled = savable
        scanQr.setOnClickListener {
            if (bookings.pending != null || unusablePending) return@setOnClickListener
            receiveDeviceQr = { url, key ->
                if (view.parent === container) {
                    qrBase = url
                    qrKey = key
                    address.setText(url.toString())
                    code.text.clear()
                    code.hint = "Gerätecode aus QR-Code übernommen"
                    feedback.isVisible = true
                    feedback.text = "Bitte die Serveradresse prüfen und die Verbindung bestätigen."
                }
            }
            if (!DeviceQrScanner.start(this)) {
                receiveDeviceQr = null
                feedback.isVisible = true
                feedback.text = "Die Kamera ist hier nicht verfügbar. Serveradresse und Gerätecode können von Hand eingegeben werden."
            }
        }
        view.findViewById<Button>(R.id.btnSaveBaseUrl).apply {
            isEnabled = savable
            setOnClickListener {
                if (bookings.pending != null) return@setOnClickListener
                val base = validatedBase(address.text.toString())
                val enteredCode = code.text.toString().trim()
                val scannedCode = qrKey.takeIf { qrBase != null && qrBase == base }.orEmpty()
                val newCode = enteredCode.ifEmpty { scannedCode }
                val oldBase = validatedBase(settings.getString(BASE_PREF, DEFAULT_BASE).orEmpty())
                val existingCode = keyStore.read()
                val deviceCode = newCode.ifEmpty { existingCode.takeIf { oldBase == base }.orEmpty() }
                feedback.isVisible = true
                if (base == null) {
                    feedback.text = "Bitte eine gültige HTTPS-Serveradresse eingeben."
                    return@setOnClickListener
                }
                if (deviceCode.isEmpty()) {
                    feedback.text = "Bitte den Gerätecode eingeben, der auf diesem Server für dieses Gerät registriert wurde."
                    return@setOnClickListener
                }
                if (!deviceCode.matches(Regex("[!-~]{8,256}"))) {
                    feedback.text = "Der Gerätecode hat ein ungültiges Format."
                    return@setOnClickListener
                }
                val useExternalScanner = useHid.isChecked
                isEnabled = false
                reset.isEnabled = false
                scanQr.isEnabled = false
                address.isEnabled = false
                code.isEnabled = false
                useHid.isEnabled = false
                feedback.text = "Serververbindung wird geprüft …"
                val screen = screenGeneration
                OdentalerApi(base, deviceCode).request("bootstrap") { reply ->
                    onScreen(screen) {
                        isEnabled = savable
                        reset.isEnabled = savable
                        scanQr.isEnabled = savable
                        address.isEnabled = true
                        code.isEnabled = true
                        useHid.isEnabled = true
                        val config = if (reply.successful) decodeEvent(reply.objectBody()) else null
                        if (config == null) {
                            feedback.text = reply.setupIssue()
                            return@onScreen
                        }
                        if (bookings.pending != null || unusablePending) {
                            feedback.text = "Bitte zuerst die offene Buchung klären."
                            return@onScreen
                        }
                        val editor = settings.edit().putString(BASE_PREF, base.toString())
                            .putBoolean(HID_PREF, useExternalScanner)
                        val saved = if (newCode.isEmpty()) editor.commit() else keyStore.save(deviceCode, editor)
                        if (saved) showHome(config)
                        else feedback.text = "Die Serververbindung konnte nicht sicher gespeichert werden."
                    }
                }
            }
        }
        view.findViewById<Button>(R.id.btnResetBaseUrl).apply {
            isEnabled = savable
            setOnClickListener {
                trackDialog(AlertDialog.Builder(this@MainActivity)
                    .setTitle("Serververbindung entfernen?")
                    .setNegativeButton("Abbrechen", null)
                    .setPositiveButton("Entfernen") { _, _ ->
                        if (bookings.pending == null && keyStore.clear(settings.edit().remove(BASE_PREF))) {
                            showHome()
                        } else notifyUser("Die Serververbindung konnte nicht entfernt werden.")
                    }
                    .create())
            }
        }
    }

    private fun configureAdminTabs(page: View, container: FrameLayout, settingsView: View) {
        val session = areaSession ?: return
        val api = api() ?: return
        page.findViewById<View>(R.id.adminTabs).isVisible = true
        page.findViewById<View>(R.id.tabProducts).isVisible = false
        page.findViewById<View>(R.id.tabUsers).isVisible = false
        page.findViewById<Button>(R.id.tabSettings).setOnClickListener {
            container.removeAllViews()
            container.addView(settingsView)
        }
        page.findViewById<Button>(R.id.tabCounter).apply {
            text = "Kassenübersicht"
            setOnClickListener {
                AdminReportView(this@MainActivity, api, session.token, ::formatTokens, ::notifyUser, ::saveCsv).show(container)
            }
        }
    }

    private fun saveCsv(csv: String) {
        csvForExport = csv
        val picker = Intent(Intent.ACTION_CREATE_DOCUMENT)
            .addCategory(Intent.CATEGORY_OPENABLE)
            .setType("text/csv")
            .putExtra(Intent.EXTRA_TITLE, "odentaler-transaktionen.csv")
        try {
            @Suppress("DEPRECATION")
            startActivityForResult(picker, SAVE_CSV_REQUEST)
        } catch (_: android.content.ActivityNotFoundException) {
            csvForExport = null
            notifyUser("Auf diesem Gerät ist keine Dateiauswahl verfügbar.")
        }
    }

    private fun renderAdminAreas(page: View) {
        val session = areaSession ?: return
        val api = api() ?: return
        val parent = page as LinearLayout
        val wineRow = page.findViewById<View>(R.id.wineSwitchRow)
        val mobile = Switch(this).apply {
            text = "Mobile Bedienung aktivieren"
            minHeight = (48 * resources.displayMetrics.density).toInt()
        }
        parent.addView(mobile, parent.indexOfChild(wineRow) + 1)
        val switches = mapOf("wine" to page.findViewById<Switch>(R.id.switchWine), "mobile" to mobile)
        switches.values.forEach { it.isEnabled = false }
        val screen = screenGeneration
        api.request("admin/areas", token = session.token) { reply ->
            onScreen(screen) {
                val areas = reply.objectBody()
                if (!reply.successful || areas == null) {
                    notifyUser("Die Bereiche konnten nicht geladen werden.")
                    return@onScreen
                }
                for ((area, control) in switches) {
                    var saved = areas.optBoolean(area)
                    control.isChecked = saved
                    control.isEnabled = true
                    control.setOnCheckedChangeListener { _, enabled ->
                        if (saved != enabled) {
                            control.isEnabled = false
                            val payload = JSONObject().put("enabled", enabled).toString()
                            api.request("admin/areas/$area", "PUT", payload, session.token) { result ->
                                onScreen(screen) {
                                    if (result.successful) saved = enabled
                                    else {
                                        control.isChecked = saved
                                        notifyUser("Die Änderung konnte nicht bestätigt werden.")
                                    }
                                    control.isEnabled = true
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    private fun showCash() {
        val view = installLayout(R.layout.view_kasse)
        view.findViewById<Button>(R.id.btnBackKasse).setOnClickListener { leaveScreen() }
        view.findViewById<Button>(R.id.btnLoadTokens).apply {
            text = "Guthaben aufladen"
            setOnClickListener { openAmountDialog(refund = false) }
        }
        view.findViewById<Button>(R.id.btnRefund).setOnClickListener { openAmountDialog(refund = true) }
        renderSalesState()
    }

    private fun showCounter(area: String) {
        val view = installLayout(R.layout.view_theke)
        view.findViewById<Button>(R.id.btnBackTheke).setOnClickListener { leaveScreen() }
        view.findViewById<Button>(R.id.btnPay).setOnClickListener { confirmSale() }
        view.findViewById<Button>(R.id.btnCancel).setOnClickListener {
            if (cart.isEmpty()) cancelScan()
            else trackDialog(AlertDialog.Builder(this)
                .setTitle("Warenkorb verwerfen?")
                .setNegativeButton("Weiter bestellen", null)
                .setPositiveButton("Verwerfen") { _, _ -> cancelScan() }
                .create())
        }
        title = when (area) {
            "drinks" -> "Getränketheke"
            "food" -> "Essenstheke"
            "wine" -> "Weintheke"
            else -> "Mobile Bedienung"
        }
        renderSalesState()
    }

    private fun startScanner() {
        nfc.stop()
        hid.stop()
        if (isHidEnabled()) {
            hid.start()
            hid.observeConnection(this) {
                if (canScan()) showMessage("Bluetooth-Scanner getrennt. Bitte Verbindung prüfen.")
                else if (areaSession?.area?.let { it != ADMIN } == true) {
                    notifyUser("Bluetooth-Scanner getrennt. Bitte Verbindung prüfen.")
                }
            }
        } else nfc.start()
    }

    private fun canScan(): Boolean =
        active && areaSession?.area?.let { it != ADMIN } == true && dialog == null &&
            !requestRunning && bookings.pending == null && !unusablePending && scan == null && !scanLoading

    private fun acceptScan(uid: String) {
        if (!canScan() || !scanDebouncer.accept(uid, SystemClock.elapsedRealtime())) return
        val session = areaSession ?: return
        val api = api() ?: return
        val event = eventConfig ?: return
        val screen = screenGeneration
        val generation = ++scanGeneration
        val scanRequestedAt = SystemClock.elapsedRealtime()
        scanLoading = true
        clearMessage()
        renderSalesState()
        api.request("scans", "POST", JSONObject().put("uid", uid).toString(), session.token) { reply ->
            onScreen(screen) {
                if (generation != scanGeneration) return@onScreen
                scanLoading = false
                val body = reply.objectBody()
                val id = body?.optString("scan_id")?.takeIf(::validUuid)
                val balance = body?.optLong("balance_cents", -1) ?: -1
                if (!reply.successful || body?.optString("uid") != uid || id == null || balance < 0) {
                    renderSalesState()
                    when (reply.error) {
                        "session_unauthorized" -> {
                            showHome()
                            notifyUser("Bitte den Bereich erneut öffnen.")
                        }
                        "account_not_found" -> showMessage("Dieses Armband ist nicht registriert.")
                        else -> showMessage("Das Armband konnte nicht gelesen werden. Bitte Verbindung prüfen.")
                    }
                    return@onScreen
                }
                val remaining = body.optLong("expires_in_ms", 0).coerceIn(0, event.timeoutMillis)
                val deadline = scanRequestedAt + remaining
                if (deadline <= SystemClock.elapsedRealtime()) {
                    renderSalesState()
                    showMessage("Die Scanzeit ist abgelaufen. Bitte das Armband erneut scannen.")
                    return@onScreen
                }
                scan = Scan(id, balance, deadline)
                scheduleExpiry(event.timeoutMillis)
                if (session.area != CASH) loadProducts(api, session, screen, generation)
                else renderSalesState()
            }
        }
    }

    private fun loadProducts(api: OdentalerApi, session: AreaSession, screen: Long, generation: Long) {
        scanLoading = true
        renderSalesState()
        api.request("products", token = session.token) { reply ->
            onScreen(screen) {
                if (generation != scanGeneration) return@onScreen
                scanLoading = false
                val catalog = if (reply.successful) decodeProducts(reply.arrayBody()) else null
                if (catalog == null) {
                    cancelScan()
                    showMessage("Die Produkte konnten nicht geladen werden. Bitte Verbindung prüfen.")
                } else {
                    products = catalog
                    renderSalesState()
                }
            }
        }
    }

    private fun renderSalesState() {
        val session = areaSession ?: return
        if (session.area == ADMIN) return
        val activeScan = scan
        val pending = bookings.pending
        val scanReady = activeScan != null && SystemClock.elapsedRealtime() < activeScan.deadline && !scanLoading
        val ready = scanReady && !requestRunning && pending == null
        val prompt = when {
            requestRunning -> "Buchung wird geprüft …"
            pending != null -> "Buchung noch offen."
            scanLoading -> "Armband wird geprüft …"
            !isHidEnabled() && !nfc.isAvailable -> "Dieses Gerät hat keinen NFC-Leser."
            !isHidEnabled() && !nfc.isEnabled -> "Bitte NFC in Android aktivieren."
            else -> "Bitte Armband scannen."
        }
        if (session.area == CASH) {
            mainContent.findViewById<TextView>(R.id.kasseScanHint)?.apply {
                isVisible = !scanReady && pending == null
                text = prompt
            }
            mainContent.findViewById<TextView>(R.id.uidInfo)?.apply {
                isVisible = scanReady
                text = activeScan?.let { "Guthaben  ${formatTokens(it.balanceCents)}" }.orEmpty()
            }
            mainContent.findViewById<Button>(R.id.btnLoadTokens)?.isEnabled = ready
            mainContent.findViewById<Button>(R.id.btnRefund)?.isEnabled = ready && (activeScan?.balanceCents ?: 0) > 0
            return
        }

        mainContent.findViewById<LinearLayout>(R.id.productList)?.apply {
            removeAllViews()
            if (scanReady) {
                var category: String? = null
                for (product in products) {
                    if (product.category.isNotBlank() && product.category != category) {
                        category = product.category
                        addView(TextView(this@MainActivity).apply {
                            text = category
                            textSize = 20f
                        })
                    }
                    val row = layoutInflater.inflate(R.layout.item_product_row, this, false)
                    row.findViewById<TextView>(R.id.txtProductName).text = product.name
                    row.findViewById<TextView>(R.id.txtProductPrice).text = formatTokens(product.priceCents)
                    val quantity = row.findViewById<TextView>(R.id.txtQty)
                    val minus = row.findViewById<Button>(R.id.btnMinus)
                    val plus = row.findViewById<Button>(R.id.btnPlus)
                    fun updateQuantity(count: Int) {
                        quantity.text = count.toString()
                        minus.isEnabled = ready && count > 0
                        plus.isEnabled = ready && count < 999
                    }
                    minus.contentDescription = "${product.name} entfernen"
                    plus.contentDescription = "${product.name} hinzufügen"
                    minus.setOnClickListener { changeQuantity(product, -1)?.let(::updateQuantity) }
                    plus.setOnClickListener { changeQuantity(product, 1)?.let(::updateQuantity) }
                    updateQuantity(cart[product.id] ?: 0)
                    addView(row)
                }
                if (products.isEmpty()) addView(TextView(this@MainActivity).apply { text = "Für diesen Bereich sind keine Produkte freigegeben." })
            }
        }
        renderTotals(prompt)
    }

    private fun changeQuantity(product: Product, delta: Int): Int? {
        if (validScan() == null) return null
        val count = ((cart[product.id] ?: 0) + delta).coerceIn(0, 999)
        if (count == 0) cart.remove(product.id) else cart[product.id] = count
        renderTotals("")
        return count
    }

    private fun renderTotals(prompt: String) {
        val activeScan = scan
        val total = cartTotal()
        mainContent.findViewById<TextView>(R.id.tokenDisplay)?.text = if (activeScan == null || scanLoading) prompt
            else "Guthaben  ${formatTokens(activeScan.balanceCents)}\nWarenkorb  ${formatTokens(total)}"
        mainContent.findViewById<TextView>(R.id.tokenWarning)?.apply {
            isVisible = activeScan != null && total > activeScan.balanceCents
            text = "Guthaben reicht nicht aus."
        }
        mainContent.findViewById<Button>(R.id.btnPay)?.isEnabled =
            activeScan != null && total in 1..activeScan.balanceCents &&
                !requestRunning && !scanLoading && bookings.pending == null
        mainContent.findViewById<Button>(R.id.btnCancel)?.isEnabled =
            activeScan != null && !requestRunning && bookings.pending == null
    }

    private fun cartTotal(): Long = products.sumOf { it.priceCents * (cart[it.id] ?: 0) }

    private fun openAmountDialog(refund: Boolean) {
        val band = validScan() ?: return
        val fullRefund = band.balanceCents.takeIf { it > 0 }
        val amount = EditText(this).apply {
            hint = "z. B. 12,5 Token"
            keyListener = DigitsKeyListener.getInstance("0123456789,.")
            setRawInputType(InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL)
            setSingleLine()
        }
        val form = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            val padding = (24 * resources.displayMetrics.density).toInt()
            setPadding(padding, 0, padding, 0)
            addView(TextView(this@MainActivity).apply { text = "Guthaben  ${formatTokens(band.balanceCents)}" })
            val amounts = if (refund) listOfNotNull(fullRefund)
                else eventConfig?.presetCents.orEmpty().filter(::isHalfTokenAmount)
            amounts.take(8).chunked(2).forEach { pair ->
                addView(LinearLayout(this@MainActivity).apply {
                    pair.forEach { cents ->
                        addView(Button(this@MainActivity).apply {
                            text = when {
                                refund && !isHalfTokenAmount(cents) -> "Restguthaben ${formatTokens(cents)}"
                                refund -> "Gesamt ${formatTokens(cents)}"
                                else -> formatTokens(cents)
                            }
                            setOnClickListener { amount.setText(tokenInputText(cents)) }
                        }, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
                    }
                })
            }
            addView(amount)
        }

        val picker = AlertDialog.Builder(this)
            .setTitle(if (refund) "Wie viele Token auszahlen?" else "Wie viele Token aufladen?")
            .setView(form)
            .setNegativeButton("Abbrechen", null)
            .setPositiveButton("Weiter", null)
            .create()
        trackDialog(picker)
        picker.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
            val cents = parseTokenEntry(amount.text.toString(), refundBalance = fullRefund.takeIf { refund })
            if (cents == null) {
                amount.error = if (refund) "Halbe oder ganze Token bis zum Guthaben wählen. Das volle Restguthaben ist ebenfalls möglich."
                    else "Bitte halbe oder ganze Token eingeben."
            } else {
                picker.dismiss()
                val kind = if (refund) "refund" else "topup"
                confirmBooking(
                    band,
                    if (refund) "${formatTokens(cents)} auszahlen?" else "${formatTokens(cents)} aufladen?",
                    if (refund) "Nach der Bestätigung das Bargeld ausgeben." else "Bitte erst buchen, wenn das Bargeld entgegengenommen wurde.",
                    JSONObject().put("kind", kind).put("scan_id", band.id)
                        .put("amount_cents", cents).put("payment_method", "cash")
                )
            }
        }
    }

    private fun confirmSale() {
        val band = validScan() ?: return
        val total = cartTotal()
        if (total !in 1..band.balanceCents) return
        val selected = products.mapNotNull { product ->
            val quantity = cart[product.id] ?: return@mapNotNull null
            product to quantity
        }
        val note = selected.joinToString("\n") { (product, quantity) -> "${product.name} × $quantity" }
        val items = JSONArray()
        selected.forEach { (product, quantity) ->
            items.put(JSONObject().put("product_id", product.id).put("quantity", quantity)
                .put("unit_price_cents", product.priceCents))
        }
        confirmBooking(
            band, "${formatTokens(total)} abbuchen?", note,
            JSONObject().put("kind", "sale").put("scan_id", band.id).put("items", items),
            note
        )
    }

    private fun confirmBooking(band: Scan, title: String, message: String, payload: JSONObject, note: String = "") {
        trackDialog(AlertDialog.Builder(this)
            .setTitle(title)
            .setMessage(message)
            .setNegativeButton("Abbrechen", null)
            .setPositiveButton("Buchung bestätigen") { _, _ ->
                if (validScan() != band) {
                    notifyUser("Die Scanzeit ist abgelaufen. Bitte erneut scannen.")
                    return@setPositiveButton
                }
                val session = areaSession ?: return@setPositiveButton
                val api = api() ?: return@setPositiveButton
                val pending = bookings.begin(session.eventId, session.area, payload.toString())
                if (pending == null) {
                    showMessage("Die Buchung konnte nicht sicher vorbereitet werden.")
                    return@setPositiveButton
                }
                requestRunning = true
                renderSalesState()
                postBooking(api, session, pending, screenGeneration, note)
            }
            .create())
    }

    private fun postBooking(api: OdentalerApi, session: AreaSession, pending: PendingBooking, screen: Long, note: String = "") {
        api.request("transactions", "POST", pending.payload, session.token, pending.key) { reply ->
            onScreen(screen) { processBooking(pending, reply, note) }
        }
    }

    private fun showPending() {
        val pending = bookings.pending ?: return
        val session = areaSession ?: return
        if (pending.eventId != session.eventId || pending.area != session.area) return
        val check = View.OnClickListener { recoverBooking(pending, session) }
        if (session.area == CASH) {
            mainContent.findViewById<Button>(R.id.btnLoadTokens)?.apply {
                text = "Buchung prüfen"
                isEnabled = !requestRunning
                setOnClickListener(check)
            }
        } else {
            mainContent.findViewById<Button>(R.id.btnPay)?.apply {
                text = "Buchung prüfen"
                isEnabled = !requestRunning
                setOnClickListener(check)
            }
        }
        showMessage("Buchung noch offen. Bitte erst prüfen.\nReferenz ${pending.key.takeLast(8)}")
    }

    private fun recoverBooking(pending: PendingBooking, session: AreaSession) {
        val api = api() ?: return
        if (requestRunning || pending != bookings.pending) return
        requestRunning = true
        renderSalesState()
        showMessage("Buchung wird geprüft …")
        val screen = screenGeneration
        api.request("transactions/${pending.key}", token = session.token) { reply ->
            onScreen(screen) {
                if (bookingAction(reply.status, reply.error, confirmed = false, lookup = true) == BookingAction.RETRY_SAME) {
                    postBooking(api, session, pending, screen)
                } else processBooking(pending, reply, note = "")
            }
        }
    }

    private fun processBooking(pending: PendingBooking, reply: ApiReply, note: String) {
        requestRunning = false
        if (!active) return
        val body = reply.objectBody()
        val id = body?.optString("id")?.takeIf(::validUuid)
        val booked = body?.optLong("amount_cents", -1) ?: -1
        val balance = body?.optLong("balance_after_cents", -1) ?: -1
        val priorBalance = body?.optLong("balance_before_cents", -1) ?: -1
        val kind = body?.optString("kind")
        val payload = JSONObject(pending.payload)
        val expectedKind = payload.optString("kind")
        val expected = if (expectedKind == "sale") {
            val lines = payload.getJSONArray("items")
            (0 until lines.length()).sumOf { index ->
                val line = lines.getJSONObject(index)
                line.getLong("unit_price_cents") * line.getInt("quantity")
            }
        } else payload.optLong("amount_cents", -1)
        val balanceChange = if (kind == "topup") balance - priorBalance else priorBalance - balance
        val confirmed = reply.successful && id != null && booked > 0 && booked == expected &&
            balance >= 0 && priorBalance >= 0 && balanceChange == booked && kind == expectedKind
        val outcome = bookingAction(reply.status, reply.error, confirmed)
        if (outcome == BookingAction.UNRESOLVED || !bookings.finish(pending.key)) {
            clearScan()
            renderSalesState()
            showPending()
            if (reply.error == "session_unauthorized") notifyUser("Bitte zurückgehen und den Bereich erneut öffnen.")
            return
        }

        val area = areaSession?.area ?: return
        if (area == CASH) showCash() else showCounter(area)
        if (confirmed) {
            val confirmation = when (kind) {
                "topup" -> "Aufgeladen  ${formatTokens(booked)}"
                "refund" -> "Auszahlung verbucht  ${formatTokens(booked)}"
                else -> "Bezahlt  ${formatTokens(booked)}"
            }
            val detail = if (note.isBlank()) "" else "\n$note"
            showMessage("$confirmation\nNeues Guthaben  ${formatTokens(balance)}$detail", success = true)
        } else {
            showMessage(when (reply.error) {
                "insufficient_balance" -> "Guthaben reicht nicht aus. Bitte erneut scannen."
                "balance_limit" -> "Der Betrag überschreitet das erlaubte Guthaben."
                "invalid_token_step" -> "Bitte halbe oder ganze Token wählen und erneut scannen."
                "price_changed" -> "Ein Preis wurde geändert. Bitte Bestellung neu erfassen."
                "product_unavailable" -> "Ein Produkt ist nicht mehr verfügbar. Bitte Bestellung neu erfassen."
                "scan_expired", "scan_closed", "scan_not_found" -> "Die Scanzeit ist abgelaufen. Bitte erneut scannen."
                else -> "Die Buchung wurde abgelehnt. Bitte erneut scannen."
            })
        }
    }

    private fun validScan(): Scan? = scan?.takeIf {
        !scanLoading && !requestRunning && bookings.pending == null && SystemClock.elapsedRealtime() < it.deadline
    }

    private fun scheduleExpiry(timeout: Long) {
        val band = scan ?: return
        val expiry = Runnable {
            if (scan == band) {
                if (bookings.pending == null) {
                    dialog?.dismiss()
                    cancelScan()
                    showMessage("Die Scanzeit ist abgelaufen. Bitte das Armband erneut scannen.")
                } else {
                    clearScan()
                    renderSalesState()
                }
            }
        }
        scanExpiry = expiry
        mainHandler.postDelayed(expiry, (band.deadline - SystemClock.elapsedRealtime()).coerceIn(0, timeout))
    }

    private fun cancelScan() {
        val session = areaSession
        val id = scan?.id
        clearScan()
        renderSalesState()
        if (id != null && session != null) {
            val api = api() ?: return
            val screen = screenGeneration
            val generation = scanGeneration
            scanLoading = true
            renderSalesState()
            api.request("scans/$id", "DELETE", token = session.token) {
                onScreen(screen) {
                    if (generation == scanGeneration) {
                        scanLoading = false
                        renderSalesState()
                    }
                }
            }
        }
    }

    private fun clearScan() {
        scanGeneration++
        scanExpiry?.let(mainHandler::removeCallbacks)
        scanExpiry = null
        scan = null
        scanLoading = false
        cart.clear()
        products = emptyList()
        if (::hid.isInitialized) hid.reset()
    }

    private fun leaveScreen() {
        if (requestRunning) {
            notifyUser("Bitte warten, bis die Buchung geprüft ist.")
            return
        }
        if (cart.isNotEmpty() && bookings.pending == null) {
            trackDialog(AlertDialog.Builder(this)
                .setTitle("Warenkorb verwerfen?")
                .setNegativeButton("Weiter bestellen", null)
                .setPositiveButton("Verwerfen") { _, _ -> cancelScan(); showHome() }
                .create())
            return
        }
        if (bookings.pending == null) cancelScan()
        showHome()
    }

    private fun showMessage(text: String, success: Boolean = false) {
        clearMessage()
        val banner = mainContent.findViewById<TextView>(R.id.kasseStatusCard)
            ?: mainContent.findViewById(R.id.orderNote) ?: return
        banner.text = text
        banner.isVisible = true
        banner.setTextColor(if (success) 0xff116135.toInt() else 0xff8f2b15.toInt())
        if (success) {
            val hide = Runnable { banner.isVisible = false }
            messageExpiry = hide
            mainHandler.postDelayed(hide, 120_000L)
        }
    }

    private fun clearMessage() {
        messageExpiry?.let(mainHandler::removeCallbacks)
        messageExpiry = null
        if (::mainContent.isInitialized) {
            mainContent.findViewById<TextView>(R.id.kasseStatusCard)?.isVisible = false
            mainContent.findViewById<TextView>(R.id.orderNote)?.isVisible = false
        }
    }

    private fun trackDialog(newDialog: AlertDialog) {
        hid.reset()
        dialog?.dismiss()
        dialog = newDialog
        newDialog.setOnKeyListener { _, _, event ->
            isHidEnabled() && hid.onKeyEvent(event, captureEnabled = false)
        }
        newDialog.setOnDismissListener { if (dialog === newDialog) dialog = null }
        newDialog.show()
    }

    private fun onScreen(screen: Long, action: () -> Unit) = runOnUiThread {
        if (!isFinishing && !isDestroyed && screenGeneration == screen) action()
    }

    private fun api(): OdentalerApi? {
        val key = keyStore.read() ?: return null
        val url = validatedBase(settings.getString(BASE_PREF, DEFAULT_BASE).orEmpty()) ?: return null
        return OdentalerApi(url, key)
    }

    private fun validatedBase(value: String): HttpUrl? {
        val input = value.trim()
        val address = if ("://" in input) input else "https://$input"
        return address.toHttpUrlOrNull()?.takeIf {
            it.isHttps && it.username.isEmpty() && it.password.isEmpty() && it.query == null && it.fragment == null
        }
    }

    private fun notifyUser(text: String) = Toast.makeText(this, text, Toast.LENGTH_LONG).show()

    private fun isHidEnabled() = settings.getBoolean(HID_PREF, false)

    private fun decodeEvent(json: JSONObject?): EventConfig? {
        if (json == null) return null
        val id = json.optString("event_id").takeIf(String::isNotBlank) ?: return null
        val areas = json.optJSONArray("areas") ?: return null
        val values = json.optJSONArray("topup_amounts_cents") ?: JSONArray()
        val timeout = json.optLong("scan_timeout_seconds", 120).takeIf { it in 1..3600 } ?: return null
        return EventConfig(
            id,
            json.optString("event_name"),
            (0 until areas.length()).map { areas.optString(it) }.toSet(),
            timeout * 1000,
            (0 until values.length()).map { values.optLong(it) }.filter { it > 0 }
        )
    }

    private fun decodeProducts(json: JSONArray?): List<Product>? {
        if (json == null) return null
        return runCatching {
            (0 until json.length()).map { index ->
                val item = json.getJSONObject(index)
                val price = item.getLong("price_cents")
                require(price in 1..Int.MAX_VALUE.toLong())
                Product(item.getInt("id"), item.getString("name"), price, item.optString("category"))
            }
        }.getOrNull()
    }

    private fun decodePending(json: JSONObject): PendingBooking {
        val key = json.getString("key")
        require(validUuid(key))
        val payload = json.getString("payload")
        require(JSONObject(payload).optString("kind") in setOf("topup", "refund", "sale"))
        return PendingBooking(key, json.getString("eventId"), json.getString("area"), payload)
    }

    private fun encodePending(booking: PendingBooking): String = JSONObject()
        .put("key", booking.key)
        .put("eventId", booking.eventId)
        .put("area", booking.area)
        .put("payload", booking.payload)
        .toString()

    private fun validUuid(value: String): Boolean = runCatching {
        UUID.fromString(value).toString() == value
    }.getOrDefault(false)

    private companion object {
        const val CASH = "cash"
        const val ADMIN = "admin"
        const val BASE_PREF = "apiBaseUrl"
        const val HID_PREF = "useHidScanner"
        const val PENDING_PREF = "pendingV1Booking"
        const val HAD_SCAN_STATE = "hadScanState"
        const val DEFAULT_BASE = "https://cashless.local"
        const val SAVE_CSV_REQUEST = 120
    }
}
