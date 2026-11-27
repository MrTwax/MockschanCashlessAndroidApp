package com.mockschan.cashless

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class TokenAmountTest {
    @Test fun topupsUseWholeOrHalfTokens() {
        assertEquals(1050L, parseTokenEntry("10,50"))
        assertEquals(50L, parseTokenEntry("0.5"))
        assertEquals(100L, parseTokenEntry("1"))
        assertNull(parseTokenEntry("0,01"))
        assertNull(parseTokenEntry("3,40"))
    }

    @Test fun formatsAndRefundsLegacyAmountsExactly() {
        assertEquals("12,37 Token", formatTokens(1237))
        assertEquals("1.001,5 Token", formatTokens(100150))
        assertEquals("12,37", tokenInputText(1237))
        assertEquals(1237L, parseTokenEntry("12,37", refundBalance = 1237))
        assertEquals(50L, parseTokenEntry("0,5", refundBalance = 1237))
        assertNull(parseTokenEntry("12,87", refundBalance = 1237))
        assertNull(parseTokenEntry("12,27", refundBalance = 1237))
    }

    @Test fun rejectsInexactOrUnusableAmounts() {
        assertNull(parseTokenEntry("0.001"))
        assertNull(parseTokenEntry("1e3"))
        assertNull(parseTokenEntry("-3"))
        assertNull(parseTokenEntry("0"))
        assertNull(parseTokenEntry("1000000000000"))
    }
}
