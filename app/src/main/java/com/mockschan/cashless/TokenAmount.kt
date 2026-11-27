package com.mockschan.cashless

import java.math.BigDecimal
import java.text.NumberFormat
import java.util.Locale

private const val HALF_TOKEN_UNITS = 50L
private val tokenInput = Regex("[0-9]{1,12}(\\.[0-9]{1,2})?")

internal fun isHalfTokenAmount(units: Long): Boolean = units > 0 && units % HALF_TOKEN_UNITS == 0L

internal fun parseTokenEntry(input: String, refundBalance: Long? = null): Long? {
    val decimal = input.trim().replace(',', '.')
    if (!tokenInput.matches(decimal)) return null

    val units = BigDecimal(decimal).movePointRight(2).longValueExact()
    if (units <= 0 || (refundBalance != null && units > refundBalance)) return null
    return units.takeIf { isHalfTokenAmount(it) || it == refundBalance }
}

internal fun tokenInputText(units: Long): String =
    BigDecimal.valueOf(units, 2).stripTrailingZeros().toPlainString().replace('.', ',')

internal fun formatTokens(units: Long): String {
    val formatter = NumberFormat.getNumberInstance(Locale.GERMANY).apply { maximumFractionDigits = 2 }
    return "${formatter.format(BigDecimal.valueOf(units, 2))} Token"
}
