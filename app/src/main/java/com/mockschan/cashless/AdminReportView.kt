package com.mockschan.cashless

import android.app.Activity
import android.app.AlertDialog
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Locale
import java.util.TimeZone

internal class AdminReportView(
    private val activity: Activity,
    private val api: OdentalerApi,
    private val token: String,
    private val money: (Long) -> String,
    private val notify: (String) -> Unit,
    private val export: (String) -> Unit
) {
    fun show(container: FrameLayout) {
        val scroll = ScrollView(activity)
        val controls = LinearLayout(activity).apply {
            orientation = LinearLayout.VERTICAL
            val padding = (16 * resources.displayMetrics.density).toInt()
            setPadding(padding, padding, padding, padding)
        }
        scroll.addView(controls)
        container.removeAllViews()
        container.addView(scroll)

        val labels = arrayOf("Heute", "Letzte 7 Tage", "Letzte 30 Tage")
        val options = intArrayOf(1, 7, 30)
        val dateButton = Button(activity)
        val exportButton = Button(activity).apply { text = "Transaktionen als CSV speichern" }
        val body = TextView(activity).apply { textSize = 18f }
        controls.addView(dateButton)
        controls.addView(exportButton)
        controls.addView(body)
        var generation = 0
        var query = reportQuery(1)

        fun load(index: Int) {
            val request = ++generation
            query = reportQuery(options[index])
            dateButton.text = "Zeitraum · ${labels[index]}"
            exportButton.isEnabled = false
            body.text = "Abrechnung wird geladen …"
            api.request("admin/report", token = token, query = query) { reply ->
                activity.runOnUiThread {
                    if (activity.isDestroyed || scroll.parent !== container || generation != request) return@runOnUiThread
                    val report = if (reply.successful) reply.objectBody() else null
                    body.text = report?.let(::formatReport) ?: "Abrechnung konnte nicht geladen werden."
                    exportButton.isEnabled = report != null
                }
            }
        }

        dateButton.setOnClickListener {
            AlertDialog.Builder(activity)
                .setTitle("Abrechnungszeitraum")
                .setItems(labels) { _, index -> load(index) }
                .setNegativeButton("Abbrechen", null)
                .show()
        }
        exportButton.setOnClickListener {
            val request = generation
            exportButton.isEnabled = false
            api.request("admin/transactions.csv", token = token, query = query) { reply ->
                activity.runOnUiThread {
                    if (activity.isDestroyed || scroll.parent !== container || generation != request) return@runOnUiThread
                    exportButton.isEnabled = true
                    val csv = reply.body
                    if (reply.successful && !csv.isNullOrBlank()) export(csv)
                    else notify(if (reply.status == 422) "Zu viele Einträge. Bitte einen kürzeren Zeitraum wählen." else "CSV konnte nicht geladen werden.")
                }
            }
        }

        load(0)
    }

    private fun formatReport(report: JSONObject): String = buildString {
        val topups = report.optLong("cash_topups_cents")
        val refunds = report.optLong("cash_refunds_cents")
        appendLine("Baraufladungen  ${money(topups)}")
        appendLine("Barauszahlungen  ${money(refunds)}")
        appendLine("Barzufluss nach Auszahlungen  ${money(topups - refunds)}")
        appendLine("Warenverkäufe  ${money(report.optLong("sales_cents"))}")
        appendLine("Offenes Guthaben aktuell  ${money(report.optLong("outstanding_balance_cents"))}")
        appendLine("${report.optLong("transaction_count")} Buchungen")
        for ((key, title) in listOf("by_area" to "Verkäufe je Bereich", "by_product" to "Verkäufe je Produkt", "by_device" to "Verkäufe je Gerät")) {
            val rows = report.optJSONArray(key) ?: continue
            if (rows.length() == 0) continue
            appendLine()
            appendLine(title)
            for (index in 0 until rows.length()) {
                val row = rows.optJSONObject(index) ?: continue
                val name = when (key) {
                    "by_area" -> when (val area = row.optString("area")) {
                        "drinks" -> "Getränketheke"
                        "food" -> "Essenstheke"
                        "wine" -> "Weintheke"
                        "mobile" -> "Mobile Bedienung"
                        else -> area
                    }
                    "by_product" -> "${row.optString("product_name")} × ${row.optLong("quantity")}"
                    else -> row.optString("name")
                }
                appendLine("$name  ${money(row.optLong("sales_cents"))}")
            }
        }
    }.trimEnd()

    private fun reportQuery(days: Int): Map<String, String> {
        val utc = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.ROOT).apply {
            timeZone = TimeZone.getTimeZone("UTC")
        }
        val until = Calendar.getInstance()
        val from = (until.clone() as Calendar).apply {
            add(Calendar.DATE, 1 - days)
            set(Calendar.HOUR_OF_DAY, 0)
            set(Calendar.MINUTE, 0)
            set(Calendar.SECOND, 0)
            set(Calendar.MILLISECOND, 0)
        }
        if (from.timeInMillis >= until.timeInMillis) until.add(Calendar.MILLISECOND, 1)
        return mapOf("from" to utc.format(from.time), "until" to utc.format(until.time))
    }
}
