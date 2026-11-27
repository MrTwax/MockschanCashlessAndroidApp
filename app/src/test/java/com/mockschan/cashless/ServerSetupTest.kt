package com.mockschan.cashless

import java.net.SocketTimeoutException
import java.net.UnknownHostException
import javax.net.ssl.SSLHandshakeException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ServerSetupTest {
    @Test
    fun networkErrorsKeepTheirCause() {
        assertEquals(ConnectionFailure.DNS, ApiReply.networkError(UnknownHostException()).connectionFailure)
        assertEquals(ConnectionFailure.TLS, ApiReply.networkError(SSLHandshakeException("test")).connectionFailure)
        assertEquals(ConnectionFailure.TIMEOUT, ApiReply.networkError(SocketTimeoutException()).connectionFailure)
    }

    @Test
    fun setupDistinguishesRejectedCodeFromMissingApi() {
        assertTrue(ApiReply(401, null).setupIssue().contains("Gerätecode"))
        assertTrue(ApiReply(404, null).setupIssue().contains("/v1"))
    }
}
