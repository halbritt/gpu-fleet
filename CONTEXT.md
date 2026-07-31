# GPU fleet

The GPU fleet separates what the owner wants available from what the fleet can
currently prove and safely offer.

## Language

**Declared slot**:
An owner-selected topology and policy entry in `fleet_nodes`.
_Avoid_: Capability measurement, live slot

**Measured slot**:
A heartbeat-owned observation of one endpoint and GPU capability in `gpu_slots`.
_Avoid_: Desired slot, configured node

**Routable slot**:
A measured slot that is fresh, alive, and graduated. Lease availability and
request headroom are separate claim predicates.
_Avoid_: Healthy node, available GPU

**Lease**:
A time-bounded, fenced admission record written for an intentional fleet
consumer. A lease is not an estimate of GPU use.
_Avoid_: Reservation hint, occupancy observation

**Foreign occupancy**:
Measured GPU use that has no fleet lease identity.
_Avoid_: Shadow lease

**Physical resource**:
The GPU capacity shared by one or more logical slots.
_Avoid_: Slot
