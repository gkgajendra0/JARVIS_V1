# Step 3 — India Privacy and Domestic-Use Context

**Status:** RESEARCH CONTEXT — NOT LEGAL ADVICE — NOT IMPLEMENTATION AUTHORITY  
**Date:** 2026-08-30

This note records the current India-specific privacy boundary for JARVIS V1 so biometric design decisions are not made as if the project existed outside a legal context.

## 1. Current project context

JARVIS V1 is currently a personal, locally operated assistant on the owner's own Windows computer. Step 3 proposes local face/speaker embeddings, local liveness evidence, and local authority/audit state. It does not propose cloud biometric recognition, public surveillance, or persistent profiling of unknown people.

## 2. DPDP Act personal/domestic-purpose exclusion

Section 3(c)(i) of India's Digital Personal Data Protection Act, 2023 states that the Act does not apply to personal data processed by an individual for any personal or domestic purpose.

For the current personal-use JARVIS deployment, that exclusion is highly relevant. It should not be interpreted as a reason to retain unnecessary biometric data or ignore consent/privacy engineering. JARVIS still follows data minimization because biometric templates are difficult to replace if exposed and because the product scope may change later.

Official source:

- https://www.meity.gov.in/static/uploads/2024/02/Digital-Personal-Data-Protection-Act-2023.pdf

## 3. DPDP Rules and phased commencement

The Digital Personal Data Protection Rules, 2025 were notified in November 2025. The associated commencement notification phases different provisions of the Act/Rules over immediate, one-year, and eighteen-month periods.

Official sources:

- https://www.meity.gov.in/documents/act-and-policies/digital-personal-data-protection-rules-2025-gDOxUjMtQWa
- https://www.meity.gov.in/static/uploads/2025/11/c56ceae6c383460ca69577428d36828b.pdf

This research does not attempt to provide a formal compliance determination because the current personal/domestic project is outside the ordinary commercial-data-fiduciary posture and because legal applicability depends on the actual future use, distribution, and processing relationships.

## 4. JARVIS engineering rule despite the exclusion

The technical privacy controls remain mandatory architectural requirements even when the personal/domestic exclusion applies:

- raw camera frames and microphone audio used for identity are memory-only by default;
- unknown people are never persistently enrolled in Step-3 v1;
- owner biometric templates are encrypted locally;
- enrollment and deletion are explicit owner operations;
- audit records exclude raw embeddings/media/secrets and retain only bounded redacted security metadata;
- debug/benchmark media requires deliberate development use and is not a production retention path;
- local benchmark samples from another person require that person's informed permission;
- no biometric identity data is sent to an LLM/cloud provider by default.

These are product-security/privacy choices, not claims that the DPDP Act currently requires every one of them for this domestic deployment.

## 5. Scope-change gate

A fresh privacy/legal review becomes mandatory before any of the following scope changes are accepted:

- distributing or selling JARVIS to other people;
- operating JARVIS for a business, employer, organization, or client;
- persistent guest/family/bystander identity profiles;
- cloud storage or cloud processing of biometric templates/media;
- remote biometric identification;
- surveillance/passive-world-awareness features that persist or share identifiable third-party data;
- cross-device biometric profile synchronization;
- using recorded third-party biometric data to train or benchmark models beyond explicit personal testing;
- commercial deployment of models whose weight/training-data licenses or provenance remain uncertain.

At that gate, review the then-current DPDP Act/Rules commencement state, notices/consent/rights/security obligations, applicable sectoral rules, cross-border processing, biometric model/data licenses, and any other jurisdictions in which JARVIS is offered or used.

## 6. Research conclusion

The current India personal/domestic-use context does not require weakening Step-3 privacy controls. The architecture should continue to behave as though biometric data is sensitive: minimize it, encrypt what must persist, keep identity local, avoid bystander profiles, and make deletion possible.

This note is contextual engineering research only and is not legal advice or a statement of formal regulatory compliance.
