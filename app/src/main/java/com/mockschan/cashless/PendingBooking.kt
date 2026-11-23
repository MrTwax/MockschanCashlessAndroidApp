package com.mockschan.cashless

import java.math.BigDecimal
import java.util.UUID

internal data class PendingBooking(
    val key: String,
    val eventId: String,
    val area: String,
    val payload: String
)

internal interface BookingStore {
    fun read(): PendingBooking?
    fun save(booking: PendingBooking?): Boolean
}

internal class BookingGuard(private val store: BookingStore) {
    val pending: PendingBooking? get() = synchronized(lock) { store.read() }

    fun begin(eventId: String, area: String, payload: String): PendingBooking? = synchronized(lock) {
        if (store.read() != null) return null
        val booking = PendingBooking(UUID.randomUUID().toString(), eventId, area, payload)
        booking.takeIf { store.save(it) }
    }

    fun finish(key: String): Boolean = synchronized(lock) {
        store.read()?.key == key && store.save(null)
    }

    private companion object {
        val lock = Any()
    }
}

internal enum class BookingAction { CONFIRMED, REJECTED, RETRY_SAME, UNRESOLVED }

internal fun bookingAction(status: Int, error: String?, confirmed: Boolean, lookup: Boolean = false): BookingAction =
    when {
        status in 200..299 && confirmed -> BookingAction.CONFIRMED
        lookup && status == 404 && error == "transaction_not_found" -> BookingAction.RETRY_SAME
        status in 400..499 && error in finalBookingErrors -> BookingAction.REJECTED
        else -> BookingAction.UNRESOLVED
    }

private val finalBookingErrors = setOf(
    "invalid_request", "invalid_uid", "invalid_idempotency_key", "account_not_found",
    "scan_not_found", "scan_expired", "scan_closed", "insufficient_balance", "product_unavailable",
    "price_changed", "unsupported_payment_method", "balance_limit"
)

internal fun parsePositiveCents(input: String): Long? {
    val decimal = input.trim().replace(',', '.')
    if (!decimal.matches(Regex("[0-9]{1,12}(\\.[0-9]{1,2})?"))) return null
    return runCatching {
        BigDecimal(decimal).movePointRight(2).longValueExact().takeIf { it > 0 }
    }.getOrNull()
}
