---
status: accepted
---

# Keep owner intent declared and runtime truth measured

`fleet_nodes` declares owner intent: which topology is enabled, which endpoint
and access path to try, which capability is wanted, and which probe and routing
policy apply. `gpu_slots` and its companion tables record what a heartbeat can
currently observe. Observations can suppress routing and fence consumers, but
must not silently rewrite owner intent. Lease columns are reserved for real,
intentional admissions; an observer must not manufacture a lease to represent
foreign occupancy.

## Consequences

- Model choice stays declared. Discovery, liveness, context support, throughput,
  residency, and foreign occupancy are measured facts.
- A competence battery may publish separate attestations only when a current
  consumer needs them and the probe has a non-interfering execution budget. It
  must not choose or rewrite the configured model.
- Foreign processes may reduce measured capacity. They do not become synthetic
  lease holders. A fleet-owned process that needs hard exclusion must use a real
  lease on the shared physical resource.
- Multiple logical slots on one GPU do not prove independent capacity. A future
  resource-level lease design must model that relationship explicitly rather
  than writing another slot's lease columns from a heartbeat.

## Considered options

- Inferring the configured model from benchmarks was rejected because a
  benchmark cannot recover owner intent such as peecee's required vision model.
- Writing synthetic leases for observed processes was rejected because the
  observer would become a second writer to the fencing record. Foreign use can
  reduce measured capacity without claiming a fleet admission occurred.
- A rotating competence battery remains possible as a separate attestation,
  but only for a named consumer and only when its probe cannot block leased
  work.
