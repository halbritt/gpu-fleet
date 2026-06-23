# FALSIFIER - RFC 0002 build plan challenge

author: falsifier-openai-codex-gpt-5.5-003

## Claim Challenged

The attempt-3 build plan claims that it can satisfy the RFC's peecee pull-only gate while retiring the fragile cross-host SSH `nvidia-smi` leg:

- Section 4 says the build does not need to touch peecee's shared GPU: no probe, no decode, no `nvidia-smi`, no SSH.
- Section 5 says retiring cross-host SSH `nvidia-smi` is only a one-row `fleet_nodes` data step because peecee's liveness already comes from the HTTP `ollama-ondemand` endpoint.
- Q5 says the pull-only, no-uuid GPU-swap case is covered by Pillar 6 trust-tiering plus load-aware liveness, while an explicit lower-trust tag is out of scope.

Those statements are incompatible with the live code the plan is supposed to realize. The current `ollama-ondemand` path still requires `gpu_stats(gpu_cmd)` before it can ever report peecee alive.

## Concrete Counterexample

Apply the attempt-3 plan as written:

1. The operator applies migration `009`, deploys the writer, and follows the named Section-5 data step: remove peecee slot 0's cross-host SSH `nvidia-smi` command from `fleet_nodes.gpu_cmd`.
2. `heartbeat_all.probe_node` still begins every peecee probe by calling `gpu_stats(n["gpu_cmd"], GPU_TIMEOUT)`.
3. `gpu_stats` is not an HTTP endpoint reader. It shells a command and appends the `nvidia-smi` CSV flags; a no-SSH/no-`nvidia-smi` command returns an error or no parsed `gpu_model`.
4. `ollama_ondemand_liveness` immediately returns `alive=False` when `gpu_err is not None` or `stats.get("gpu_model") is None`, before it can use `/api/ps` residency or any endpoint-level liveness.
5. The row written for peecee is therefore `alive=false`; it cannot accumulate `probe_streak`, cannot graduate, and is absent from `routable_slots` once Slice 4 gates consumers on `status='routable'`.

That refutes the gate claim that peecee "runs zero fleet code/creds, is still monitored (pull), and is correctly de-listed when marker owns the card." Under the plan, peecee is de-listed whenever the SSH `nvidia-smi` leg is actually retired, independent of marker.

The opposite branch is also bad: if the holder leaves `gpu_cmd='ssh -o BatchMode=yes peecee nvidia-smi'` in place so load-aware liveness keeps working, then the build has not retired the exact cross-host SSH fan-out the RFC and the attempt-3 plan both name as the live-infra boundary.

## Evidence From The Artifacts And Source

The RFC's settled design says the pull floor is the existing inference HTTP endpoint, so peecee participates with zero fleet code and zero DB credentials. It also says a pull-only node with no independent `nvidia-smi` has endpoint-asserted, lower-trust VRAM, and that only the cross-host SSH fan-out dies.

Attempt 3 repeats that promise. Section 5 says dropping peecee's SSH `gpu_cmd` is a one-row `fleet_nodes` update because peecee's liveness already comes from `ollama-ondemand`. Q5 then puts the residual pull-only GPU-swap case in Pillar 6 / load-aware liveness rather than adding a schema column.

The live code does not support that data step:

- `heartbeat_all.probe_node` calls `gpu_stats(n["gpu_cmd"], GPU_TIMEOUT)` for every node, then passes `stats` and `gpu_err` into `ollama_ondemand_liveness`.
- `gpu_stats` appends `--query-gpu=...` and `--format=csv,noheader,nounits`; it is specifically an `nvidia-smi` parser, local or over SSH.
- `ollama_ondemand_liveness` fails closed before residency checks when GPU stats are unavailable: `if gpu_err is not None or stats.get("gpu_model") is None: return False, None, None`.
- The migrations leave peecee slot 0 with `probe_model='ollama-ondemand'` and the original SSH `gpu_cmd`; there is no planned replacement path that reads endpoint-asserted VRAM from HTTP or marks that signal as lower trust.

## Why The Planned Tests Do Not Prove The Gate

The planned test K only asserts that the pull path writes through the driver's DB connection and stamps `boot_epoch` NULL. Existing load-aware tests prove the marker-owned-card case only when fake `gpu_stats` supplies the VRAM observation. They do not exercise the actual attempt-3 data step: peecee is pull-only, no SSH, no `nvidia-smi`, and still monitored through HTTP.

A discharging test is straightforward:

1. Build a peecee slot 0 row with `probe_model='ollama-ondemand'` and no SSH / no `nvidia-smi` `gpu_cmd`, matching the Section-5 data step.
2. Stub the HTTP endpoint as resident or loadable through the mechanism the plan intends to trust.
3. Run the planned `probe_node` / UPSERT path.
4. Assert no SSH or `nvidia-smi` command is invoked, `alive=True` when the endpoint is serveable, `boot_epoch` remains NULL, and the row can graduate to `routable`; also assert marker-owned/not-loadable still writes `alive=False`.

With the currently described plan, that test fails at step 3/4 because `gpu_stats` fails first and `ollama_ondemand_liveness` returns `alive=False` before checking endpoint residency.

## Strongest Rebuttal I Can Justify

The holder can argue that `ollama_ondemand_liveness` already calls `/api/ps`, so peecee's liveness is HTTP-based enough. That is not what the code does. The `/api/ps` branch is reached only after `gpu_stats` succeeds and provides a GPU model / VRAM observation. A warm resident model still reports dead if the SSH `nvidia-smi` command is removed.

The holder can also argue that the data step could replace `gpu_cmd` with some other local command that returns `nvidia-smi`-shaped CSV via HTTP. That mechanism is not in the plan, is not in the tests, and would still need to define the endpoint-asserted/lower-trust source the RFC explicitly calls out. As written, the plan says peecee liveness already comes from HTTP, but the code path still depends on an `nvidia-smi`-shaped side channel.

## Unanswered Gap

The plan must choose and test one coherent implementation:

- implement an HTTP-only peecee pull path that obtains endpoint-asserted residency / loadability without SSH or `nvidia-smi`, records or otherwise enforces its lower trust, and proves peecee can still graduate and de-list correctly when marker owns the card; or
- keep the existing `nvidia-smi` side channel and narrow the RFC/plan claim so peecee is not actually zero-SSH pull-only in v1.

Until that is specified, the build cannot satisfy both the live-infra boundary and the peecee falsifiable gate. Retiring SSH makes peecee disappear; retaining SSH violates the settled zero-touch/pull-only boundary the plan claims to preserve.
