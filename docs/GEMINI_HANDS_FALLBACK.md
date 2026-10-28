# Hands planning fallback

When Gemini paid fallback is enabled and the paid credential is available,
a Hands planning request that receives HTTP 503 from the free-configured
credential proceeds directly to one paid planning attempt. It does not first
retry the free request. This uses standard processing; it does not enable
Priority inference.

The 503 is recorded as `service_unavailable_http_503` for exact admission
evidence. It does not establish quota exhaustion or put subsequent requests
into paid-only routing. The next independent request starts with free again,
subject to existing quota state.

Existing quota/rate-limit fallback remains in place. The new 503 edge applies
only to Hands planning, not realtime voice, Work, or memory. Paid failure stops
the current invocation. Existing once-only invocation and action protections
remain in force. With fallback disabled or the paid target unavailable,
existing free transient-error handling remains in place.

Paid service can also fail. This fallback provides another attempt, without
guaranteeing availability or eliminating time spent on the initial free request.
