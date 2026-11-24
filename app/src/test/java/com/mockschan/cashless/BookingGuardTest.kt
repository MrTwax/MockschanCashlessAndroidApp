package com.mockschan.cashless

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class BookingGuardTest {
    @Test fun duplicatesCannotReplaceAnUnconfirmedBooking() {
        val store = MemoryStore()
        val guard = BookingGuard(store)
        val first = guard.begin("19", "cash", """{"kind":"topup","amount_cents":1250}""")
        assertNotNull(first)
        assertNull(guard.begin("19", "cash", """{"kind":"topup","amount_cents":1250}"""))
        assertNull(BookingGuard(store).begin("20", "food", """{"kind":"sale"}"""))
        assertEquals(first, store.value)
    }

    @Test fun appRestartReopensTheSameKeyAndPayload() {
        val store = MemoryStore()
        val first = BookingGuard(store).begin("19", "cash", """{"kind":"refund","amount_cents":500}""")!!
        val reopened = BookingGuard(store)
        assertEquals(first, reopened.pending)
        assertFalse(reopened.finish("different-key"))
        assertTrue(reopened.finish(first.key))
        assertNull(reopened.pending)
    }

    @Test fun failedStoragePreventsSubmissionAndFailedClearingKeepsTheAttempt() {
        val store = MemoryStore()
        val guard = BookingGuard(store)
        store.fail = true
        assertNull(guard.begin("19", "cash", "{}"))
        store.fail = false
        val booking = guard.begin("19", "cash", "{}")!!
        store.fail = true
        assertFalse(guard.finish(booking.key))
        assertEquals(booking, guard.pending)
    }

    @Test fun interruptedRequestAndMalformedSuccessRemainUnresolved() {
        assertEquals(BookingAction.UNRESOLVED, bookingAction(0, null, confirmed = false))
        assertEquals(BookingAction.UNRESOLVED, bookingAction(503, null, confirmed = false))
        assertEquals(BookingAction.UNRESOLVED, bookingAction(200, null, confirmed = false))
        assertEquals(BookingAction.UNRESOLVED, bookingAction(401, "session_unauthorized", confirmed = false))
        assertEquals(BookingAction.UNRESOLVED, bookingAction(409, "idempotency_conflict", confirmed = false))
    }

    @Test fun lookupRequestsReplayOnlyForExplicitUnknownKey() {
        assertEquals(BookingAction.RETRY_SAME, bookingAction(404, "transaction_not_found", confirmed = false, lookup = true))
        assertEquals(BookingAction.UNRESOLVED, bookingAction(404, null, confirmed = false, lookup = true))
        assertEquals(BookingAction.UNRESOLVED, bookingAction(404, "transaction_not_found", confirmed = false))
        assertEquals(BookingAction.CONFIRMED, bookingAction(200, null, confirmed = true, lookup = true))
        assertEquals(BookingAction.REJECTED, bookingAction(409, "insufficient_balance", confirmed = false, lookup = true))
        assertEquals(BookingAction.REJECTED, bookingAction(400, "invalid_token_step", confirmed = false))
    }

    private class MemoryStore : BookingStore {
        var value: PendingBooking? = null
        var fail = false

        override fun read(): PendingBooking? = value

        override fun save(booking: PendingBooking?): Boolean {
            if (fail) return false
            value = booking
            return true
        }
    }
}
