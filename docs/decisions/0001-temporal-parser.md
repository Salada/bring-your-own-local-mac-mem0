# Decision 0001: defer a temporal parser dependency

- Status: Accepted
- Date: 2026-09-11
- Scope: local temporal extraction and query parsing

## Context

The runtime needs Korean and English support for absolute dates, relative dates,
calendar spans, and durations. Those are not all the same problem:

- `last week` identifies a calendar interval;
- `for three hours` identifies a scalar duration;
- `worked there for three years until 2024` also requires linking that duration
  to an event or state and deciding its validity interval.

A rule-based parser can solve the first two classes, but it does not by itself
provide the event semantics required by the third.

## Options considered

- [dateparser](https://dateparser.readthedocs.io/en/stable/) is Python-native,
  BSD-licensed, supports more than 200 locales including
  [Korean](https://dateparser.readthedocs.io/en/stable/supported_locales.html),
  accepts a fixed `RELATIVE_BASE`, and can return spans such as `last week`.
  Its own documentation warns that date search in longer text needs improvement
  and can produce false positives.
- [Duckling](https://github.com/facebook/duckling) has structured `Time` and
  `Duration` dimensions and Korean time rules, but requires a Haskell build or a
  separate local service. Its documentation also notes that dimensions vary by
  language, so Korean time support does not imply equal Korean duration coverage.
- [HeidelTime](https://github.com/HeidelTime/heideltime) produces TIMEX3 and has
  automatically generated resources for more than 200 languages, but its
  hand-written set does not include Korean. The generated resources are described
  as lower quality, and adopting it adds Java/UIMA plus GPL-3.0 considerations.
- [Microsoft Recognizers-Text](https://github.com/microsoft/Recognizers-Text)
  supports date/time and durations, but documents Korean DateTime as partial and
  describes its Python package as alpha.

## Decision

Do not add a parser dependency in the first temporal-reasoning release. Keep the
cheap Korean/English cue detector and use the already configured LLM for the
structured interval plus event intent.

`dateparser` is the preferred first candidate for a future deterministic fast
path. It fits the Python runtime and local-only packaging substantially better
than a Duckling or HeidelTime sidecar. It must not replace the LLM fallback until
fixed Korean and English fixtures demonstrate correct spans, timezones, negative
controls, and duration behavior.

## Consequences and revisit criteria

- Temporal queries currently add one configured-LLM call; ordinary queries add
  none.
- The LLM remains responsible for connecting time expressions to occurrence or
  plan semantics.
- Revisit when a fixture corpus contains enough repeated expressions to measure
  parser coverage. Adopt `dateparser` only if it resolves the common path locally
  while falling back cleanly for ambiguous, recurring, duration-linked, and
  ongoing-state queries.
