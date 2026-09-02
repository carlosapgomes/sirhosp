# portal-shell-freshness Delta — `topbar-census-freshness`

## ADDED Requirements

### Requirement: Topbar freshness shows the latest census photo

The portal shell topbar SHALL display the capture time of the latest census
snapshot (`CensusSnapshot` with maximum `captured_at`) on every authenticated
page, labeled "Censo:", and SHALL NOT derive freshness from individual
ingestion runs nor from the request time.

#### Scenario: Authenticated page renders the census photo time

- **WHEN** an authenticated user opens any page using the portal shell
- **THEN** the topbar badge shows "Censo: HH:MM" with the latest snapshot
  `captured_at` in local timezone
- **AND** the value equals what the dashboard "Última varredura completa"
  card shows for the same moment

#### Scenario: Photo older than today shows the date

- **WHEN** the latest snapshot `captured_at` is not from the current local
  date
- **THEN** the badge shows "Censo: dd/mm HH:MM"

#### Scenario: No snapshot yet

- **WHEN** no `CensusSnapshot` exists
- **THEN** the badge shows "--:--" with the outdated dot class

#### Scenario: Individual ingestion runs never feed the badge

- **WHEN** any page renders
- **THEN** no query reads `IngestionRun` to compute the badge value

### Requirement: Freshness dot reflects photo age

The topbar freshness indicator SHALL expose the age of the latest census
photo through closed presentation classes, with the full timestamp always
available in the badge tooltip.

#### Scenario: Fresh photo

- **WHEN** the latest snapshot `captured_at` is within 2 hours
- **THEN** the dot uses the fresh class

#### Scenario: Aging photo

- **WHEN** the latest snapshot `captured_at` is older than 2 hours but
  within 6 hours
- **THEN** the dot uses the stale class

#### Scenario: Outdated or missing photo

- **WHEN** the latest snapshot `captured_at` is older than 6 hours or no
  snapshot exists
- **THEN** the dot uses the outdated class

#### Scenario: Tooltip always carries the full timestamp

- **WHEN** the badge renders with any age class
- **THEN** its `title` attribute contains the full local timestamp
  (day, month, year and time) of the latest census photo

### Requirement: Badge refreshes without page reload

The topbar badge SHALL refresh itself periodically via a lightweight
authenticated fragment endpoint, so the displayed freshness does not depend
on page loads.

#### Scenario: Authenticated poll returns the self-rearming fragment

- **WHEN** an authenticated request hits the badge fragment endpoint
- **THEN** the response is the badge HTML fragment containing the same
  periodic `hx-get`, `hx-trigger` and `hx-swap` attributes
- **AND** the badge keeps refreshing without a full page reload

#### Scenario: Anonymous poll does not swap login into the badge

- **WHEN** an anonymous request hits the badge fragment endpoint
- **THEN** the response is 401 without any login page body
- **AND** no authentication redirect is followed into the badge area

#### Scenario: Badge cost is bounded

- **WHEN** any page or badge poll renders the badge
- **THEN** exactly one aggregated snapshot query resolves the freshness
  value, independent of cohort size or run history
