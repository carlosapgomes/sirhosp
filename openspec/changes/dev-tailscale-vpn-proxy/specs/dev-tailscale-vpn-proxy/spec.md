# ADDED Specification: dev-tailscale-vpn-proxy

## Requirements

### Requirement: Dev VPN access shall be container-scoped

The development environment SHALL provide access to the hospital network only
from application containers and SHALL NOT require the host to join the Tailscale
VPN.

#### Scenario: Host remains outside the VPN

- **GIVEN** the developer runs the development Compose stack
- **WHEN** Tailscale connectivity is enabled for the application
- **THEN** Tailscale runs as a container sidecar
- **AND** the host operating system is not configured as a Tailscale node by this
  project

### Requirement: Tailscale sidecar shall be compatible with Docker rootless

The development Tailscale sidecar SHALL use userspace networking and SHALL NOT
require privileged container features.

#### Scenario: Sidecar starts without kernel TUN privileges

- **GIVEN** Docker runs in rootless mode
- **WHEN** the development stack starts the Tailscale sidecar
- **THEN** the sidecar uses userspace networking
- **AND** it does not require `/dev/net/tun`
- **AND** it does not require `NET_ADMIN`, `NET_RAW`, `privileged`, or host
  networking

### Requirement: Playwright shall use the VPN through an optional proxy

The Playwright connectors SHALL support an optional proxy configuration for
HTTP/HTTPS access to the source system while preserving current behavior when no
proxy is configured.

#### Scenario: Proxy disabled

- **GIVEN** `PLAYWRIGHT_PROXY_SERVER` is unset or empty
- **WHEN** a Playwright connector launches Chromium
- **THEN** Chromium is launched without a proxy option
- **AND** existing source URL, credentials and certificate handling behavior are
  unchanged

#### Scenario: Proxy enabled

- **GIVEN** `PLAYWRIGHT_PROXY_SERVER` is set to a SOCKS5 proxy endpoint
- **WHEN** a Playwright connector launches Chromium
- **THEN** Chromium is launched with a Playwright proxy configuration using that
  endpoint
- **AND** the connector still navigates to `SOURCE_SYSTEM_URL`
- **AND** HTTPS certificate errors remain ignored according to existing connector
  behavior

### Requirement: Development Compose shall expose a Tailscale SOCKS5 proxy

The development Compose configuration SHALL include a Tailscale sidecar that
accepts subnet routes and exposes a SOCKS5 proxy only inside the Compose network.

#### Scenario: Sidecar provides internal proxy

- **GIVEN** `TS_AUTHKEY` is provided through the environment
- **WHEN** the development stack starts
- **THEN** the sidecar authenticates to Tailscale using userspace mode
- **AND** it accepts advertised subnet routes
- **AND** it exposes a SOCKS5 proxy address reachable by application containers

### Requirement: Operational validation shall avoid sensitive data

The project SHALL document or provide a safe smoke validation that checks network
reachability without logging into the source system or persisting sensitive
responses.

#### Scenario: Smoke test checks reachability only

- **GIVEN** the development Tailscale sidecar is running
- **WHEN** the smoke validation is executed
- **THEN** it tests `SOURCE_SYSTEM_URL` reachability through the proxy
- **AND** it does not use source system username or password
- **AND** it does not store real source system response bodies in the repository
