# METHOD_AUDIT: method-level architecture audit of the fork's concept-erasure script (task SR-02)

**Auditor:** fork-auditor. **Date:** 2026-11-09. **Scope:** software/numerics audit only. Nothing here asserts that the method works, reduces any capability, or is safe. No model was run, no weights were retrieved, the script was never executed.

## 0. Labels, citation keys, provenance

- **SOURCE OBSERVED** = read directly from the cited text. **INFERENCE** = reasoning from observed text, not executed. **UNKNOWN** = not determinable from the sources read.
- Citation keys:
  - `S:Ln` = line n of the fork script `erasure_teacher_student.py` (fork path `rfdiffusion_erasure_teacher_student.py`), 691 lines, sha256 `1fef6383548419a1175b1732828d04105e384e7f8fc1759d19c7b6207090f17b` (re-hashed by this auditor; matches).
  - `D:Ln` = line n of `fork_only.diff` (1342 lines). Per-file diff starts: base.yaml D:1, diffusion.py D:14, model_runners.py D:56, inference/utils.py D:169, kinematics.py D:366, util.py D:481, util_module.py D:633, new script D:646.
  - `A:<path>:Ln` = line n of that file at the common ancestor `e22092420281c644b928e64d490044dfca4f9175`, read with `git show <ancestor>:<path>` from the local RFdiffusion checkout. The checkout's HEAD is later upstream `86507b6`; it was used only to reach the ancestor object, and no claim below relies on post-ancestor upstream text.
- SOURCE OBSERVED: the 691 added lines of the diff (D:652-1342, `+` stripped) are byte-identical to the saved script, so S:Ln and the diff agree.
- Ancestor text is used for behaviour of **unmodified** upstream code. Where this document says "the fork did not modify X", the evidence is the absence of a diff hunk (hunk list in section 9).

## 1. Method in one paragraph, strictly as implemented

SOURCE OBSERVED. The script builds one persistent trainable "student" RFdiffusion sampler (S:90-94) and optimises its parameters with AdamW (S:101-106) against a per-step regression target. At each step it draws a timestep `t` (S:359-364) and a single `(pdb, contig)` pair (S:140-141; `main()` supplies one PDB with the contig `"1/A80-90"`, S:609-615). Two *freshly constructed* frozen teacher samplers (S:193, S:224) each produce an x0-prediction at `t`: `px0_cond` from a noised input in which `diffusion_mask = ~motif_mask` (S:203), and `px0_uncond` from a noised input with `diffusion_mask = ones` (S:228). The target is `px0_uncond - eta*(px0_cond - px0_uncond)` (S:286-287), rescaled per atom to `px0_uncond`'s norm with a clamp of the scale to [0.1, 2.0] (S:290-297). The student's x0-prediction for the *conditional* teacher's noised input (S:261-274) is compared to that target by a squared error times 0.01, multiplied by a residue mask built from `motif_mask`, and summed over everything then divided by the number of masked residues (S:302-311). Backward, grad-clip, step (S:370-380). Checkpoints are saved with `torch.save` (S:474). The module contains no evaluation, no held-out data, no test and no metric other than the training loss and gradient norm (S:382-386, S:492-544).

INFERENCE. The only quantity the script can report is how well the student fits its own teacher-derived regression target. It cannot, by construction, report anything about downstream design behaviour.

## 2. Teacher / student construction

| Item | SOURCE OBSERVED | Cite |
|---|---|---|
| Hyper-parameters (class defaults) | `eta=0.5, learning_rate=1e-5, warmup_steps=100, max_grad_norm=1.0` | S:36-39 |
| Hyper-parameters actually used by `main()` | `ETA = 5`, `LEARNING_RATE = 1e-6`, `NUM_STEPS = 100`, `BATCH_SIZE = 1`, `warmup_steps=20`, `max_grad_norm=10` | S:590-593, S:660-661 |
| Persistent teacher | `iu.sampler_selector(self.conf)`, `.eval()`, all params `requires_grad=False` | S:68-72 |
| Persistent student | second sampler from a fresh composed config, `.train()`, all params `requires_grad=True` | S:77-94 |
| Both load the same weights | both configs set `ckpt_override_path = checkpoint_override` (`main()`: `models/Base_ckpt.pt`) | S:58-59, S:84-85, S:586 |
| Optimizer | `AdamW(student_model.parameters(), lr, betas=(0.9,0.999), weight_decay=0.01)`; only student params | S:101-106 |
| LR schedule | `LambdaLR` with `lr_lambda(step) = step/warmup_steps` for `step < warmup_steps`, else `1.0` | S:120-127 |
| Per-step fresh teachers | `_fresh_sampler(..., trainable=False)` is called twice per step (conditional and unconditional); each calls `iu.sampler_selector` on a deep-copied config | S:156-187, S:193, S:224 |
| Student per-step | the persistent `student_sampler` is re-pointed at the current contig and its `sample_init()` is called, but `x_init_student` is then unused (see below) | S:249-257 |

Model copies (SOURCE OBSERVED from construction sites, INFERENCE for the count): `__init__` constructs 2 samplers (S:68, S:90). Each `compute_erasure_loss` call constructs 2 more (S:193, S:224). Each `sampler_selector` builds a sampler that reads the checkpoint and builds a model (ancestor: `torch.load` at A:rfdiffusion/inference/model_runners.py:183-184, `RoseTTAFoldModule(...)` at A:...:228, `load_state_dict(..., strict=True)` at A:...:234). So up to 4 full model instances can be alive at once, and 2 are constructed and then discarded every step. Whether they are freed promptly is UNKNOWN (depends on references and the allocator).

Findings:
- SOURCE OBSERVED: the persistent `teacher_sampler` / `teacher_model` is never used to compute the target. Its only later use is `self.teacher_sampler.t_step_input` (S:361). `grep teacher_sampler|teacher_model` finds only S:68, 69, 70, 71, 361.
- INFERENCE: the effective teacher at every step is a fresh copy of the original checkpoint weights (S:59 -> S:193/224), i.e. a **fixed** teacher, not an EMA or a lagged copy of the student. Consistent with a teacher that does not drift, but see the eval/train point next.
- SOURCE OBSERVED: the student is in train mode (S:92, S:265; fork-added `self.model.train()` when `enable_grad`, D:117-118) and the teachers in eval mode (S:70, S:183-185; D:119-120). SOURCE OBSERVED (ancestor): the model contains `nn.Dropout` and a custom `Dropout` that is skipped when not `self.training` (A:rfdiffusion/Attention_module.py:13,147; A:rfdiffusion/Track_module.py:21,79-80; A:rfdiffusion/util_module.py:72-81). The base config has `p_drop: 0.15` (ancestor `base.yaml:50`; checkpoint override possible, UNKNOWN). INFERENCE: if the effective `p_drop > 0`, the student (train mode) and teacher (eval mode) would differ even at identical weights, adding target noise unrelated to erasure.
- SOURCE OBSERVED: `t` is drawn with `torch.randint(1, t_step_input, (1,))` (S:359-364); the upper bound of `randint` is exclusive, so `t_step_input` itself is never drawn (INFERENCE from standard `torch.randint` semantics). `t_step_input` is `T` or `partial_T` (A:...:162-165, 402-404); with the base config `T: 50`, `partial_T: null`, this gives `t` in 1..49 (INFERENCE; subject to checkpoint-config override, section 11).
- SOURCE OBSERVED: the scheduler multiplies the LR by `lr_lambda(step) = step/warmup_steps` (S:122-124), so at construction `lr_lambda(0) = 0` and the first `optimizer.step()` runs with LR 0. INFERENCE from PyTorch `LambdaLR` semantics: that first AdamW step is a no-op for the parameters except for weight-decay terms scaled by LR (also 0), though optimizer moment state is still updated.
- SOURCE OBSERVED: `torch.autograd.set_detect_anomaly(True)` is set at every `train_step` (S:350); no seed is set anywhere (`grep seed` finds nothing in the script).
- SOURCE OBSERVED: the "student" gets its x_t from the **teacher-conditional** branch (`x_t_student = x_t.clone()...`, S:261) and its sequence from the teacher-conditional `seq_init` (S:262). The student's own `sample_init()` outputs (S:255-257) are assigned and then overwritten/unused.
- SOURCE OBSERVED: `_fresh_sampler` has a `trainable` argument whose `True` branch (S:178-181) is never exercised in the file (both call sites pass `trainable=False`).

## 3. Erasure target derivation

### 3.1 Algebra (SOURCE OBSERVED: S:286-287)

```
concept_adj = eta * (px0_cond - px0_uncond)            # S:286
target      = px0_uncond - concept_adj                 # S:287
            = px0_uncond - eta*(px0_cond - px0_uncond)
            = (1 + eta) * px0_uncond - eta * px0_cond
```
With `u = px0_uncond`, `c = px0_cond`, `d = c - u`: `target = u - eta*d`. Both `u` and `c` are `.to(device).detach()` tensors produced under `torch.no_grad()` (S:192, 218, 223, 243).

Direction: the target lies on the opposite side of `u` from `c`; it moves *away* from the conditioned prediction by `eta` times the cond-minus-uncond difference. At `eta=0` it equals `u`; at `eta=1` it equals `2u - c`. At `main()`'s `eta=5` (S:590), `target = 6u - 5c`.

Relation to classifier-free guidance (INFERENCE, standard formula, not from this repo): CFG uses `x_u + w*(x_c - x_u)`. Setting `w = -eta` gives exactly S:286-287. So the target is a CFG-style extrapolation with a **negative** guidance weight, applied to x0-predictions and used as a training target rather than at sampling time. For `eta=5`, `w=-5`, a large extrapolation. Whether the "unconditional" branch here is a calibrated unconditional model is addressed in 3.3.

### 3.2 Magnitude renormalization (SOURCE OBSERVED: S:289-297)

```
px0_uncond_norm = px0_uncond.norm(dim=-1, keepdim=True)     # S:290   shape (L,14,1)
target_norm     = target.norm(dim=-1, keepdim=True)         # S:291
scale_factor    = px0_uncond_norm / (target_norm + 1e-8)    # S:294
scale_factor    = torch.clamp(scale_factor, 0.1, 2.0)       # S:295
stable_target   = target * scale_factor                     # S:297
```
Mechanics (SOURCE OBSERVED for the formula; the consequences below are INFERENCE):
1. `norm(dim=-1)` is the Euclidean norm of each atom's xyz vector, i.e. its **distance from the coordinate origin**, one scalar per (residue, atom). It is not a norm of the residue-level displacement.
2. Unclamped case (`0.1 <= ‖u‖/(‖t‖+1e-8) <= 2`): `stable_target = ‖u‖ * t_hat` where `t_hat = target/‖target‖`. The result keeps target's **direction** from the origin and takes `u`'s **radius**. The effective displacement from `u` is `‖u‖*(t_hat - u_hat)`. Only the output **radius** equals `‖u‖`; the displacement itself generally has a radial component, namely `‖u‖*(cos θ - 1)` (along `u_hat`, where `θ` is the angle between `t` and `u` about the origin), which is zero only when `θ = 0`. Its magnitude is `‖u‖*2*sin(θ/2)`. The displacement depends on `t` only through the direction `t_hat`.
3. Consequence (INFERENCE, algebra on the S:290-297 formula; no data): the rescaling discards the magnitude of `target` and keeps only its direction `t_hat` from the origin. The map is therefore not a fixed-fraction shrink of the displacement. Cases:
   - If `c = s*u` for a scalar `s` (so `c - u` is purely radial) then `target = (1 + eta - eta*s)*u`. With `eta = 5` this is `(6 - 5s)*u`. Write `k = 6 - 5s`; then `‖target‖ = ‖u‖*|k|`, the raw scale is `1/|k|`, and `stable_target = clamp(1/|k|, 0.1, 2.0) * k * u`. So `stable_target = u` and `-u` hold **only where the clamp does not bind**, i.e. `|k|` in [0.5, 10]: `stable_target = u` for `s` in about [-0.8, 1.1] and `stable_target = -u` (the target flips through the origin) for `s` in about [1.3, 3.2]. Outside those ranges the clamp binds (item 4). Values with `u = (3,0,0)`: `s = 1.15 -> (1.5,0,0)`, `s = 1.19 -> (0.3,0,0)`, `s = 1.25 -> (-1.5,0,0)`, `s = -1 -> (3.3,0,0)`; at `s = 1.2`, `k = 0`, `target = 0` and `t_hat` is undefined (`stable_target = 0`). Example: `u = (3,0,0)`, `s = 1.5` gives `target = (6-7.5)*u = (-4.5,0,0)`, scale `3/4.5 = 0.667` (inside [0.1, 2.0]), and `stable_target = (-3,0,0)` (unclamped, so item 4 does not apply).
   - For an angular difference between `c` and `u`, the surviving displacement is `‖u‖*(t_hat - u_hat)`, whose size is set by `‖u‖` and the angle, so it **depends on where the coordinate origin is** (it is not translation-invariant).
   - Stated as a property of the target map: the pre-renormalization displacement is `-eta*d`; the post-renormalization displacement is `‖u‖*(t_hat - u_hat)`, and the two differ in both size and direction in general. Whether this is desirable is not assessed here.
4. Clamp boundaries (INFERENCE from the formula): the clamp is on the scale, not on the output.
   - If `‖t‖ < ‖u‖/2`, the raw scale exceeds 2, is clamped to 2, and `‖stable‖ = 2‖t‖ < ‖u‖`. Direction preserved (`t_hat`), magnitude **not** restored.
   - If `‖t‖ > 10‖u‖`, the raw scale is below 0.1, is clamped to 0.1, and `‖stable‖ = 0.1‖t‖ > ‖u‖`. Direction preserved, magnitude **not** restored.
   - With `eta=5` (`t = 6u - 5c`), `‖t‖` far from `‖u‖` is plausible when `c` and `u` differ; how often this happens is UNKNOWN (never measured).
   - The clamp is applied elementwise per atom, so adjacent atoms in one residue can be scaled by different factors, so **bond geometry within a residue is not preserved** in `stable_target` (INFERENCE; a per-atom dilation about the origin with atom-dependent factors is not a rigid or uniform transform).
5. Degenerate inputs (INFERENCE): `‖t‖ = 0` gives scale clamped to 2 and `stable_target = 0`. NaN anywhere in `px0_*` propagates (NaN * anything is NaN, and `clamp` does not remove NaN). Whether `px0` contains NaN at absent atoms is UNKNOWN (the fork's alignment writes NaN back at `~atom_mask` positions, D:335-337, but that can only restore NaN already present in `px0`; the ancestor did the same at A:rfdiffusion/inference/utils.py:360). INFERENCE: absent-atom slots are probably **finite placeholders**, not NaN: `xyzs_in_base_frame` is initialised with `torch.ones((22,27,4))` and `base_indices` with 0 (A:rfdiffusion/util.py:588-589), so slots not set for a residue type come from the backbone frame with a non-zero placeholder offset; such slots then enter both the loss sum and the per-atom renormalisation.
6. The scale factor is computed from detached tensors, so it adds no gradient path (SOURCE OBSERVED: inputs detached at S:218/243; `stable_target.detach()` at S:306 is redundant).
7. The code comment calls this "Option 1: Normalize to prevent explosion" (S:289). SOURCE OBSERVED: no reference value, ablation, or reason for the [0.1, 2.0] bounds exists in the file. UNKNOWN: the rationale.

### 3.3 Is the "unconditional" teacher unconditional? (new finding; SOURCE for the mechanics, INFERENCE for the conclusion)

- SOURCE OBSERVED: the two teachers are built by the same `_fresh_sampler(self.conf, parsed_pdb, pdb_path, contig_string)` call, i.e. **the same contig** (S:193, S:224; S:165-175).
- SOURCE OBSERVED (ancestor): inside `Sampler.sample_step`, the sampler's own `self.mask_str` / `self.diffusion_mask` (derived from the contig map, A:...:281-282, 335) drives the conditioning features (`timefeature[mask_str] = 1`, A:...:533-534), the template NaN masking (A:...:545), the model's `motif_mask=` argument (A:...:646) and the denoiser's `diffusion_mask` (A:...:662). The fork does not change these (no hunk, section 9).
- SOURCE OBSERVED: the script's `diffusion_mask_u = torch.ones_like(motif_mask)` (S:228) only affects how `x_t_u` is noised by `diffuse_pose` (S:230-234), not these internal sampler masks. The `seq_init_u` from `sample_init()` (S:226) still carries the motif residue identities (non-21 entries; the script itself defines motif as `argmax(seq_init) != 21`, S:201).
- INFERENCE: the "unconditional" branch differs from the conditional branch in (a) the noised-coordinate input and (b) independent random draws, not in the sampler's own motif conditioning features. Whether `px0_cond - px0_uncond` isolates a "concept" is therefore UNKNOWN, and it likely contains stochastic and input-noising differences unrelated to any concept.
- SOURCE OBSERVED: the two branches call `sample_init()` and `diffuse_pose()` independently (S:195, 205, 226, 230) with no seed (grep `seed`: none), and `sample_init` itself returns already forward-noised coordinates `xt` (ancestor `return xt, seq_t`, A:...:426-431, 465 `return xt, seq_t`), which the script then diffuses *again* to `t_int` (S:205-209). INFERENCE: `x_t` is therefore a re-noised version of a T-level noised structure; the noise level of `x_t` relative to `t` is UNKNOWN.

### 3.4 Mask polarity into `diffuse_pose` (new finding; INFERENCE, needs a generic unit test before any weight is given)

- SOURCE OBSERVED (ancestor docstring): `diffuse_pose(..., diffusion_mask ...)`: "Tensor of bools, **True means NOT diffused** at this residue, False means diffused" (A:rfdiffusion/diffusion.py:621). Also `delta[diffusion_mask, ...] = 0` (A:...:103).
- SOURCE OBSERVED (ancestor): the sampler itself passes `self.diffusion_mask` (= `mask_str`, True at motif) to `diffuse_pose` (A:model_runners.py:335, 426).
- SOURCE OBSERVED: `ContigMap`'s default `inpaint_seq` is True for non-`("_","_")` reference entries (A:rfdiffusion/contigs.py:99-101), so by default `motif_mask` (S:201) is True at motif residues (INFERENCE for this script's contig).
- SOURCE OBSERVED: the script passes `diffusion_mask = ~motif_mask` (S:203, S:207) for the conditional branch and all-`True` (S:228, S:232) for the "unconditional" branch.
- INFERENCE: under the ancestor's stated convention, the conditional branch holds **scaffold** residues fixed and noises the **motif** residues (opposite of the sampler's own usage), and the "unconditional" branch noises **nothing** (all `True` = not diffused). This is contrary to the script's own comments ("all scaffold", S:221). It may be correct if the author intended the opposite convention, but the intent is UNKNOWN. If real, `diffuse_pose` would add zero translation delta for every residue (A:rfdiffusion/diffusion.py:103), so `x_t_u` would be the recentred `sample_init` output, which is already T-noised (A:model_runners.py:428) and independent of `t_int`; it would not be noise-free and would not be noised to level `t`. Not verified by execution.

## 4. Loss and masking semantics

```
scaffold_mask = (motif_mask).float().unsqueeze(-1).unsqueeze(-1).to(device)   # S:302
element_loss  = (px0_student - stable_target.detach()) ** 2 * 0.01            # S:306
masked_loss   = element_loss * scaffold_mask                                  # S:307
valid         = scaffold_mask.sum()                                           # S:308
loss          = masked_loss.sum() / valid                                     # S:311 (if valid > 0)
```

SOURCE OBSERVED facts:
- `motif_mask` has shape `(L,)` (bool from `argmax(...) != 21`, S:201). After two `unsqueeze(-1)`, `scaffold_mask` has shape `(L,1,1)`. `px0` is `(L,14,3)` (docstring of `sample_step`, A:...:613; `px0.squeeze()[:, :14]`, D:133). The mask broadcasts over the 14 atoms and 3 coordinates.
- `0.01` is a constant factor applied to every element (S:306). It is not normalized away.
- The variable is named `scaffold_mask` but is built directly from `motif_mask` (no inversion).

Normalization mismatch (derivation; arithmetic is exact. The shape premise `(L,14,3)` is SOURCE OBSERVED: `px0 = px0.squeeze()[:,:14]` at A:model_runners.py:650 / D:133 with the docstring at A:613, `allatom` returns `(B,L,27,3)` at A:util_module.py:333-334, `motif_mask` is `(L,)` so `scaffold_mask` is `(L,1,1)`. Caveats: the derivation assumes `L > 1` (for `L = 1` the `squeeze()` would collapse a dimension), and the 14 are atom **slots**, not necessarily real atoms):
- Let `M` = number of motif residues = `scaffold_mask.sum()` = `valid`.
- `masked_loss.sum()` sums over `M x 14 x 3 = 42M` non-masked elements (masked rows contribute 0).
- The divisor is `M`, not `42M`.
- Therefore `loss = 0.01 * (sum over motif residues of sum over 14 atoms and 3 coords of delta^2) / M = 0.01 * 42 * mean_elem(delta^2) = 0.42 * mean_elem(delta^2)`, where `mean_elem` is the mean over the `42M` unmasked elements.
- The mismatch is thus a **constant factor 42 (= 14*3)** relative to a true per-element mean, not a length-dependent factor. Net multiplier relative to a per-element MSE: `0.42`; relative to a per-residue sum of squared error: `0.01`.
- Comparability across sequence lengths (INFERENCE): because the divisor is `M`, the loss is a per-motif-residue average of a fixed 42-element sum, so it does not grow with `L` through this mismatch; it does depend on which atoms are present (all 14 atom slots are summed regardless of whether the residue has 14 real atoms; INFERENCE: unused slots are finite non-zero placeholders, see 3.2 item 5, and are included in the sum) and on motif identity. Different `M` therefore changes the variance of the average, not its scale.
- The loss gradient w.r.t. `px0_student` is `0.02*delta/M` per element (analytic from S:306-311), i.e. it scales as `1/M`; with `main()` having one dataset item and one contig the value of `M` is constant (the contig `1/A80-90` fixes it only up to the sampler's own parsing; UNKNOWN).
- **No finite check:** NaN in `delta` yields NaN loss even where `scaffold_mask = 0` because `NaN * 0 = NaN` (INFERENCE from IEEE arithmetic). Whether NaN occurs is UNKNOWN (see item 5 of 3.2: absent slots are probably finite placeholders).

Empty-mask path (SOURCE OBSERVED): `else: RuntimeError` at S:312-313 is a bare expression and does not raise, so `loss` is unbound and `return loss` (S:325) would raise `UnboundLocalError` (INFERENCE from Python semantics). Consistent with FORK_AUDIT concern 1.

Reconciling with the author's "gradient is high" note: SOURCE OBSERVED: commit `12d5426`'s message says "Concept erases allow for gradient flow, but gradient is high and needs to be looked at" (SR-01, DIFF_EVIDENCE section 4). The mismatch above is a constant factor of 42 that the `0.01` multiplier more than cancels (net 0.42 versus an element-mean MSE), so by itself it does **not** explain a *high* gradient; it is at most a unit choice. INFERENCE (candidate contributors, none measured): `eta=5` extrapolation (3.1), coordinate units, per-atom renormalization amplifying small-norm atoms (clamp 2.0), student in train mode (dropout), and the fact that the logged `grad_norm` is the value returned by `clip_grad_norm_`, which for PyTorch is the **pre-clip** norm (INFERENCE from the API; `max_grad_norm=10` in `main()`, S:661, so clipping rarely engages if norms are below 10). The actual cause is UNKNOWN. UNKNOWN also: which of the two fork commits introduced the `0.01` constant (the file at `5cbd18a` is the only version read; commit 2 rewrote 15 lines, SR-01 section 3).

## 5. The comment at S:299-301 versus the code

Verbatim (S:299-301):
```
# Create scaffold mask (where we want to apply erasure), we apply loss over the conditioned mofits
# Key: MOTIF_MASK covers the elements that are instructed to stay. We move the guess away from this direction
# As such, 
```
- SOURCE OBSERVED: the comment ends mid-sentence ("As such,") and contains the typo "mofits".
- SOURCE OBSERVED: the comment is internally inconsistent. Its first clause calls the mask a "scaffold mask (where we want to apply erasure)"; its next words say the loss is applied "over the conditioned mofits" [motifs]; its second line says `MOTIF_MASK` covers the motif elements.
- SOURCE OBSERVED: the code builds the mask directly from `motif_mask` (S:302) and the loss is nonzero only at motif residues (S:307). The target moves away from the conditioned prediction (S:286-287).
- Verdict: the code **matches the "motif" reading of the comment** (loss over motif residues, target pushed away from `px0_cond`). It does **not** match the label "scaffold mask", which in RFdiffusion terminology means the non-motif residues (`~motif_mask`, as used at S:203). Which one the author intended is **UNKNOWN**. INFERENCE: since training happens only on motif residues, the scaffold residues receive no direct loss.
- Interaction with 3.4 (INFERENCE): if the `diffusion_mask` polarity at S:203 is inverted as argued, the motif residues are exactly the ones that are noised in the conditional branch, so the loss is applied to the noised residues; whether this is intended is UNKNOWN.

## 6. Gradient path

Trace (SOURCE OBSERVED unless marked):
1. `loss = masked_loss.sum()/valid` (S:311). `total_loss.backward()` (S:370).
2. `masked_loss <- element_loss * scaffold_mask` (S:307); `scaffold_mask` is a float built from a bool tensor, no grad.
3. `element_loss <- (px0_student - stable_target.detach())**2 * 0.01` (S:306). `stable_target` is a function only of `px0_cond`/`px0_uncond`, both detached and produced under `torch.no_grad()` (S:192-218, 223-243): no gradient to any teacher.
4. `px0_student <- self.student_sampler.sample_step(..., enable_grad=True)[0]` then `.to(device)` (S:268-277).
5. Inside `Sampler.sample_step` (fork-modified): `with torch.set_grad_enabled(enable_grad)` wraps the model forward and, as indented in the diff, the `self.allatom(...)` call (`with` at D:122, `allatom` at D:132-134). The fork replaced `with torch.no_grad()` with this and moved `allatom` inside it.
6. After the `with` block, `denoiser.get_next_pose(...)` returns `(x_t_1, px0)`; the script keeps only `px0` (`px0_student, _, _, _ = ...`, S:268). In `get_next_pose`, `px0` is passed through `align_to_xt_motif` when `align_motif and diffusion_mask.any()` (A:rfdiffusion/inference/utils.py:447), which the fork rewrote in torch (D:213-339), including `torch.linalg.svd`, `torch.det` and `torch.sign`. `px0` is returned at the end (A:rfdiffusion/inference/utils.py:501, `return fullatom_next.squeeze()[:, :14, :], px0`).
7. `x_t_1` goes through NumPy in `get_next_frames` (`.cpu().detach()...numpy()`, D:173-200) and is therefore detached, but it is discarded by the script and does not feed the loss.
8. Unmodified upstream code detaches rotation/translation between model blocks: `R_in = R_in.detach() # detach rotation (for stability)` and `T_in = T_in.detach()` (A:rfdiffusion/Track_module.py:415-416, 435-436, 456-457). The fork did not touch this file.

What is detached: `px0_cond`, `px0_uncond`, `stable_target` (and `scale_factor`), `x_t_1` path. What is not: `px0_student`, `element_loss`, `loss`. `x_t_student = x_t.clone().detach().requires_grad_(True)` (S:261) is a **leaf input tensor**, not a parameter; it is not in the optimizer (S:101-106).

Can end-to-end gradient flow to student **weights** be established from source alone? **No.** Reasons:
- SOURCE OBSERVED: the two checks that would have asserted it are commented out: `# if not px0_student.requires_grad: raise ...` (S:279-280) and `# if not loss.requires_grad: raise ...` (S:322-323); the diagnostic prints at S:314-317 are also commented out.
- INFERENCE: because `x_t_student` has `requires_grad=True`, `px0_student.requires_grad` and `loss.requires_grad` could be True through the *input* even if no student parameter were connected to the graph. Even the commented-out assertions, had they been enabled, would not have discriminated parameter-level flow. A discriminating check needs `any(p.grad is not None and p.grad.abs().sum() > 0 for p in student.parameters())` after `backward()`; nothing equivalent exists in the file.
- INFERENCE: `clip_grad_norm_` returns the total norm (S:373-376); a norm of exactly 0 would indicate no parameter gradient, but the script only logs it (S:384, S:430-435) and never asserts it.
- SOURCE OBSERVED: the fork's own commit message claims "Concept erases allow for gradient flow" (DIFF_EVIDENCE section 4) and the fork adds `print("model px0 grad:", px0.requires_grad)` / `print("after allatom grad:", ...)` / `print("after pose:", ...)` (D:131-157), i.e. the author probed `requires_grad` of *outputs*. Results of those prints are not in the sources: UNKNOWN. A True `requires_grad` on an output does not by itself show that parameters contribute (same input-leaf caveat).
- INFERENCE: the upstream `.detach()` calls in `Track_module` mean the gradient path is truncated through the iterated rotation/translation state, so the gradient chain **across** blocks through R/T is truncated. The detach sits at the start of each block, so R/T updates produced inside a block still carry gradient to that block's own parameters, and the final block's parameters reach `px0` directly; the extent of coverage across earlier blocks is not determined. Parameter-level gradient *magnitudes* and coverage are UNKNOWN.
- SOURCE OBSERVED (ancestor): `Sampler._preprocess` writes in place into `xyz_t`: `xyz_t[torch.where(seq == 21, True, False),3:,:] = float('nan')` when `preprocess_conf.sidechain_input` (A:model_runners.py:542-543), and the fork clones only in the `else` branch (D:77-83). `x_t_student` is a grad-requiring leaf (S:261) that is passed in as `x_t`. INFERENCE: under `sidechain_input: True` an in-place write on a leaf requiring grad would raise in PyTorch; the base config has `sidechain_input: False` (ancestor `base.yaml:117`), so this is not triggered with that config. Whether `xyz_t` inside `_preprocess` is the same tensor as `x_t` was not traced.
- Status: gradient flow to student weights is a **hypothesis supported by design intent**, not an established fact. A generic test with a synthetic module is the proper way to establish the analogous property (SR-06); establishing it for the real model would require running it (out of scope here).

## 7. Checkpoints

SOURCE OBSERVED, save (S:458-475): a Python dict containing `student_model_state_dict`, `optimizer_state_dict`, `scheduler_state_dict`, `global_step`, `losses`, `grad_norms`, `eta_values`, `config` (= `OmegaConf.to_container(self.conf, resolve=True)`), `eta`, `learning_rate`, `device`; written by `torch.save(checkpoint, path)`. Written to `checkpoint_step_{step}.pt` every `save_interval` steps (`step % save_interval == 0 and step > 0`, S:438-441) and `checkpoint_final.pt` (S:448-450). In `main()`, `save_interval=50`, `NUM_STEPS=100` (S:592, 677), so by this arithmetic one intermediate (`step_50`) and the final are written; the loop condition is INFERENCE from S:414-444.

SOURCE OBSERVED, load (S:477-490): `torch.load(path, map_location=self.device)` with no `weights_only` argument, then `load_state_dict` on student/optimizer/scheduler (default `strict=True` for the model), restores `global_step`, `losses`, `grad_norms`, `eta_values`. It does **not** restore `eta` or `learning_rate` from the file. No key-presence or version validation.

Trust / provenance:
- INFERENCE (standard PyTorch behaviour, not from this repo): `torch.load` with pickle can execute arbitrary code from an untrusted file. Whether the default `weights_only` value protects here depends on the installed PyTorch version, which this audit did not determine: UNKNOWN. The same unrestricted `torch.load` pattern exists in upstream code for model and scaffold files (A:model_runners.py:183, 821, 826), so this is not fork-specific.
- SOURCE OBSERVED: no hash, no git SHA, no version of the fork/upstream code, no random seed, no teacher-checkpoint hash, no data/PDB identity (only the config container, which may contain `ckpt_override_path` and `input_pdb` strings), no dataset record, and no date are written. The saved `config` is `self.conf` (the teacher/conf at S:52), whose `input_pdb` is not the training PDB (training PDBs are passed per step into copies, S:165). INFERENCE: a checkpoint file cannot be tied to the exact code, base weights, or training data by its own contents.
- SOURCE OBSERVED: the key is `student_model_state_dict`, whereas upstream's loader reads `self.ckpt['model_state_dict']` (A:model_runners.py:234) and reads model config from the checkpoint (`assemble_config_from_chk`, A:...:186-198 docstring refers to the checkpoint's `config_dict`). INFERENCE: a checkpoint written by this script is **not directly loadable by the unmodified upstream sampler via `ckpt_override_path`**; an adapter is needed. No such adapter is in the fork diff (SR-01: 8 files only).
- SOURCE OBSERVED: no weights file is in the fork diff (DIFF_EVIDENCE section 5). No claim about any trained checkpoint is made here, and no trained safe checkpoint exists in the sources.

## 8. Config and baseline differences

SOURCE OBSERVED (D:1-13): `config/inference/base.yaml`, `model_runner: SelfConditioning` -> `model_runner: default`; one line. The selector (A:rfdiffusion/inference/utils.py:508-512) maps `"default"` to `model_runners.Sampler` and `"SelfConditioning"` to `model_runners.SelfConditioning`.

Differences between the runners (ancestor, SOURCE OBSERVED):
- `SelfConditioning(Sampler)` overrides `sample_step` (A:model_runners.py:676-682). When `t < T` and `t != partial_T` it builds the template from `self.prev_pred` (A:...:706) and feeds it as `xyz_t`/`t2d`; it stores `self.prev_pred = torch.clone(px0)` after the forward (A:...:742). `Sampler.sample_step` (A:...:603) has no such step.
- `SelfConditioning.sample_step` hard-codes `with torch.no_grad():` (A:...:721) and has the signature `(self, *, t, x_t, seq_init, final_step)` (A:...:682); it has no `enable_grad` parameter.
- The fork's grad-enabling edit is in `Sampler.sample_step` only (hunks D:111-160, all within ancestor lines ~603-675). `SelfConditioning.sample_step` is unmodified (no hunk in A:676-785).
- In the ancestor, `prev_pred` is assigned only inside `SelfConditioning.sample_step` (A:...:742); reads are at A:706 and A:740 (A:740 is `symmetrise_prev_pred(...)` a method call; A:777 is the `def symmetrise_prev_pred` line, not the attribute).

INFERENCE on why the runner changed: the script calls `sample_step(..., enable_grad=...)` (S:211-217, 241-242, 268-274). Under `SelfConditioning` this would raise `TypeError` (unexpected keyword) and could not carry grad (`no_grad`). The one-line config change is therefore necessary **given the fork's chosen edit** (gradient enabling in `Sampler.sample_step` only); a different edit could have enabled gradients in `SelfConditioning` instead, so it is not shown to be necessary for any gradient flow. Whether it was a methodological choice is UNKNOWN. Also with `SelfConditioning` an isolated first call at `t < T` would read an unset `self.prev_pred` (AttributeError, INFERENCE), since the script constructs fresh samplers and takes a single step.

**Confound (INFERENCE).** The pre-fork default used self-conditioning (previous x0-prediction fed back); the fork's default and the script's forward do not. Self-conditioning is part of the sampler's input distribution; the checkpoint is used with a different input pipeline from the one the pre-fork config defaulted to. Any measured behavioural difference between "upstream default behaviour" and "fork-modified, trained student" can arise from (a) the runner switch, (b) the fork's other numerical/geometric edits in section 9 (they alter code paths that run for **all** users of the modified files, not only the erasure path), (c) the training itself, or (d) stochastic variation. No evidence in the sources separates these. Whether the runner change alters outputs materially is UNKNOWN.

**Baseline-equivalence experiment that would separate them (design only; not executed and not authorized by this audit).** Pre-register fixed seeds and a fixed, non-sensitive, generic evaluation input set, and compare four arms with identical sampler config and seeds:
- Arm A: upstream at the ancestor, `SelfConditioning`.
- Arm B: upstream at the ancestor, `default` runner only (isolates (a): B-A).
- Arm C: fork code with the base weights and **no training** (student = teacher weights), `default` runner (isolates (b): C-B).
- Arm D: fork code after training (isolates (c): D-C).
Report the paired differences with uncertainty across seeds, and include a utility-retention metric alongside any target metric. Separately, and runnable without any model weights, the numerical edits in section 9 can be tested on synthetic tensors by comparing original vs patched functions (alignment, angle/dihedral helpers, `c6d`) on random finite inputs, edge cases (degenerate vectors, NaN, near-zero norm) and the `g(t)` coefficient. Execution of arms A-D with real weights belongs to the human-gated SR-17 decision, not to the autonomous loop.

## 9. The seven modified upstream files (SOURCE OBSERVED from fork_only.diff; classification is INFERENCE)

Classification key: GRAD = enables or preserves autograd; NUM = numerical hardening/behaviour change; GEO = geometry code rewrite; DEV = device/dtype plumbing; CFG = configuration; DBG = debugging output.

| File (diff lines) | Hunks and mechanical effect | Class |
|---|---|---|
| `config/inference/base.yaml` (D:1-13) | `model_runner: SelfConditioning` -> `default`. | CFG (see section 8) |
| `rfdiffusion/diffusion.py` (D:14-55) | `g(t)`: former `torch.tensor(t, requires_grad=True)` / `autograd.grad` is wrapped in `with torch.enable_grad():`, uses `dtype=torch.float32`, and returns `torch.sqrt(grads).detach()` (D:31-45). A whitespace-only line change and a missing-final-newline change (D:22-23 and D:53-55). Effect: the coefficient can be computed when called inside `no_grad` and is returned without grad. Previously forced `float32`-less default dtype (INFERENCE: `torch.tensor(float)` already yields float32 by default, so the dtype argument may be a no-op for Python floats; for numpy/float64 inputs it would change dtype). | GRAD/NUM |
| `rfdiffusion/inference/model_runners.py` (D:56-168) | (i) adds module-level `gumbel_softmax_sample` (D:60-75); only the diff and the script were searched and neither contains a call (SOURCE OBSERVED: no call site in D or S); whether another file in the ancestor tree calls it was not searched, so "unused" is INFERENCE. (ii) `_preprocess`: `xyz_t = xyz_t.clone()` before in-place NaN-masking (D:77-91; SOURCE OBSERVED: the clone is only in the `else` branch, the `sidechain_input` branch writes in place, see section 6); `torch.full(...).to(xyz_t.device)` (D:88); `alpha`, `alpha_mask` moved `.to(self.device)` (D:92-101). (iii) `sample_step` gains `enable_grad=False`; `train()`/`eval()` toggled by it; `torch.no_grad()` replaced by `torch.set_grad_enabled(enable_grad)`; `allatom` call moved inside that block; three `print(...requires_grad...)` statements added; `nn.one_hot(seq_init.long(), ...)` (D:111-160). (iv) a last hunk (D:162-168) touching only the final-line newline of a later `_preprocess`. | GRAD (i not), DEV, DBG |
| `rfdiffusion/inference/utils.py` (D:169-365) | `get_next_frames`: `R_0/R_t` converted via `.cpu().detach()` before scipy (D:173-178) and the `einsum` inputs `.detach().cpu().numpy()` (D:184-200) so this path is **detached by construction** (still used for `x_t_1`, not for `px0`). `get_next_ca`: `mu`, `sigma` moved to `xt.device` (D:204-212). `align_to_xt_motif`: rewritten from NumPy/SVD to torch (Kabsch via `torch.linalg.svd`, `torch.det`, `torch.sign`), restoring NaN at missing atoms with `torch.where` (D:213-339); this **is** the path that carries gradient to `px0` when alignment runs. `get_next_pose`: a blank-line removal, `.to(xt.device)` on the potential gradient and on `frames_next` / `ca_deltas` (D:343-365). | GRAD (alignment), GEO, DEV |
| `rfdiffusion/kinematics.py` (D:366-480) | `get_ang`, `get_dih`: in-place `v /= ...` replaced by `v = v / ...` (D:370-389). `xyz_to_c6d`: docstring removed; the in-place `dist[torch.isnan(dist)] = 999.9` and `+=` diagonal replaced by `torch.where` and an out-of-place add (D:390-460). `c6d` itself is still filled by in-place indexed assignment and `c6d[...,0][c6d[...,0] >= DMAX] = 999.9` is retained with the comment "This is OK" (D:449-450). A hunk at D:461-480 edits `dist_to_onehot` (the NaN replacement becomes functional, `dist_clean`; `xyz_to_bbtor` appears only as hunk-header context). | GRAD (avoids in-place on a tensor autograd needs), NUM |
| `rfdiffusion/util.py` (D:481-632) | `th_ang_v`: replaced with a version that sanitises NaN/Inf via `nan_to_num`, zeroes invalid vectors, adds `tiny=1e-7` guards, keeps `eps` inside the `sqrt` and has a branch returning (cos, sin) = (1, 0) for entries flagged invalid (D:525-527). INFERENCE (arithmetic on the shown code): at the default `eps=1e-8`, `tiny=1e-7` that branch is **unreachable**: each norm is `sqrt(sum_sq + eps) >= 1e-4 > tiny`, and `nan_to_num` leaves all values finite, so `valid` is always True. NaN or all-zero inputs therefore yield `(cos, sin) = (0, ~1)` (vectors become 0, `cos = 0`, `sin = sqrt(1 + eps)`), i.e. a 90-degree angle, not angle 0 and not NaN. The new `sqrt(clamp_min(1-cos^2,0)+eps)` (D:522-523) is equivalent to the old `sqrt(1-cos^2+eps)` (D:535) because `cos` is already clamped to [-1,1] (D:485-540). `th_dih_v`: `nan_to_num` on inputs maps NaN to 0 *before* normalisation, so NaN or all-zero inputs yield `(cos, sin) = (0, 0)` there (norm floor `sqrt(eps)=1e-4`, normalised vectors 0, crosses 0); its (1, 0) replacement fires only if the final cos/sin are non-finite, which cannot occur after sanitising at defaults (INFERENCE) (D:541-586). `get_torsions`: `.to(xyz.device)` on index/ref tensors and on `th_ang_v` output (D:586-632). A duplicate `import torch` is added mid-file (D:489). Effect (INFERENCE): **changes returned values** for degenerate or NaN-containing inputs on every code path that calls these helpers. In particular, upstream `_preprocess` relies on NaN in `alpha` to clear `alpha_mask` (`alpha_mask = logical_and(alpha_mask, ~isnan(alpha[...,0]))`, then `alpha[isnan(alpha)] = 0`, A:rfdiffusion/inference/model_runners.py:565-566); if `get_torsions` no longer produces NaN where it used to, that model input (`alpha_mask`) changes. The size of the effect is UNKNOWN. | NUM (semantic change), DEV |
| `rfdiffusion/util_module.py` (D:633-645) | `ComputeAllAtomCoords.forward` signature gains `seq_idx=None`. Body use of the new parameter is not in the hunk (SOURCE OBSERVED: only the signature line changes). Effect: UNKNOWN (an unused argument as far as this hunk shows). | minor |
| `rfdiffusion_erasure_teacher_student.py` (D:646-1342) | The method script analysed in sections 1-7. | method |

Mechanical summary: the **gradient-enabling** edits are `Sampler.sample_step` (D:111-160), differentiable `align_to_xt_motif` (D:213-339), `g(t)` under `enable_grad` (D:27-45) and the out-of-place edits in `kinematics.py` and `_preprocess`. The **numerical/geometric** edits change behaviour for all callers: `util.py` masks invalid angles as 0 (D:485-586), `align_to_xt_motif` replaces a NumPy SVD with a torch SVD. INFERENCE: none of these were validated by any test (no test files in the diff, DIFF_EVIDENCE section 5), and equality with the pre-fork functions on valid inputs is not demonstrated; this is the (b) arm of the confound in section 8.

## 10. Claims register

| # | Claim the method could be read as making | Label | Evidence now | Evidence needed to upgrade |
|---|---|---|---|---|
| 1 | A frozen teacher and a trainable student are constructed | SOURCE OBSERVED | S:68-72, S:90-94 | none (static) |
| 2 | Teacher weights are never updated | SOURCE OBSERVED: `requires_grad=False` is set on the persistent teacher (S:71-72) and fresh teachers (S:183-185, `trainable=False`) and they are not in the optimizer (S:101-106). INFERENCE: no runtime update; not tested | static reading only | a runtime assertion that teacher params are bitwise unchanged after N steps |
| 3 | Target moves away from conditioned prediction: `(1+eta)u - eta c` | SOURCE OBSERVED | S:286-287 | none |
| 4 | This is negative-weight CFG-style extrapolation | INFERENCE | algebraic identity with `w = -eta` | author statement or reference |
| 5 | The "unconditional" branch is an unconditional model | UNKNOWN (INFERENCE against) | same contig, sampler-internal masks unchanged (3.3) | trace of every motif-dependent input of the branch, or test showing outputs differ only in the claimed way |
| 6 | The `diffusion_mask` polarity at S:203/228 is as intended | INFERENCE (appears inverted vs ancestor docstring) | A:diffusion.py:621 | unit test of `diffuse_pose` on a synthetic tensor, or author confirmation |
| 7 | Magnitude renormalization preserves the erasure signal | INFERENCE (it replaces the displacement `-eta*d` with `‖u‖(t_hat - u_hat)`, which can differ in size and direction, is origin-dependent, and can flip sign through the origin; see 3.2 items 2-4) | S:290-297 algebra | a numerical study on synthetic vectors; measurement of clamp frequency on real data (gated) |
| 8 | Clamp keeps target magnitude equal to `‖u‖` | SOURCE OBSERVED (formula) that magnitude differs from `‖u‖` when the clamp binds; occurrence rate UNKNOWN | S:294-297 | none for the formula; measurement for frequency |
| 9 | Loss is a masked per-element mean | SOURCE OBSERVED: divisor is `M`; summed elements number `42M` under shapes (L,14,3), L>1, (L,1,1) mask; 14 are slots, not necessarily atoms | S:302-311 | none for the formula |
| 10 | The mismatch explains "high gradient" | UNKNOWN | arithmetic gives net 0.42 vs element-MSE | gradient-norm decomposition on a generic model |
| 11 | Loss is applied to scaffold residues | SOURCE OBSERVED: the mask is built from `motif_mask` with no inversion | S:302 | author intent |
| 12 | Loss is applied to motif residues, matching the comment | SOURCE OBSERVED (code matches the "motif" wording) | S:299-302 | author intent for "scaffold mask" label |
| 13 | Empty-mask is handled safely | SOURCE OBSERVED: the `else` branch is a bare name and does not raise; INFERENCE: `UnboundLocalError` at S:325 if reached | S:312-313, S:325 | none |
| 14 | Gradient reaches student parameters | UNKNOWN (design intent; asserted by commit message only) | S:261 caveat, S:279-280, 322-323 commented out | per-parameter `.grad` coverage check from a generic stand-in with the same wiring (SR-06); for the real model, a gated run |
| 15 | `px0_student.requires_grad` implies parameter flow | INFERENCE: not implied (input leaf) | S:261 | n/a |
| 16 | Teachers are deterministic functions of `(pdb, contig, t)` | SOURCE OBSERVED: no seed is set and `sample_init`/`diffuse_pose` are called independently per branch; INFERENCE: outputs are stochastic | S:195, 205, 226, 230; no seed | seeded repeat comparison |
| 17 | Student and teacher compute the same function at identical weights | INFERENCE: they would differ if effective `p_drop > 0` (base config 0.15; checkpoint override UNKNOWN) | S:92, 265; D:117-120; A:Attention_module.py:13 | effective `p_drop` from the checkpoint config; equality test at step 0 |
| 18 | Training reduces loss | UNKNOWN | no curves in sources | logged runs with seeds and uncertainty |
| 19 | Training produces selective unlearning / capability reduction | UNKNOWN; no evidence of any kind | no evaluation in the fork (DIFF_EVIDENCE section 5) | independent, pre-registered capability measurements on held-out cases with controls (SR-09) |
| 20 | Benign utility is retained | UNKNOWN | none | utility metrics with CIs vs baseline |
| 21 | The method is safe / yields a safer model | UNKNOWN; not asserted by this audit | none | all of the above plus external validation and robustness (adversarial) testing |
| 22 | Behavioural differences vs upstream come from erasure | UNKNOWN (confounded) | runner change, numeric edits (sections 8-9) | four-arm design in section 8 |
| 23 | Checkpoints are attributable to specific code/base weights/data | SOURCE OBSERVED: the saved dict has no hash/SHA/seed/data identity fields | S:460-472 | add provenance metadata (SR-08 toy) |
| 24 | Saved checkpoints load in upstream inference unchanged | INFERENCE: not directly (key `student_model_state_dict` vs `model_state_dict`) | S:461; A:model_runners.py:234 | a loader adapter test on a toy state dict |
| 25 | `torch.load` of these checkpoints is safe to run on untrusted files | UNKNOWN (PyTorch version-dependent; pickle risk in general) | S:479 | pinned torch version and `weights_only=True` behaviour |
| 26 | `main()`'s run is a biosecurity evaluation | SOURCE OBSERVED: `main()` names a PDB `5TPN.pdb`, contig `1/A80-90`, description "Alpha helix motif scaffolding" (S:609-618) and contains no evaluation code; whether the example is biologically sensitive is not determinable from source | S:609-619 | n/a |

## 11. Remaining uncertainty

- UNKNOWN: runtime behaviour of everything above; no code was executed.
- SOURCE OBSERVED (ancestor `config/inference/base.yaml`, the fork's hunk touches only `model_runner`): `T: 50` (line 77), `partial_T: null` (83), `crd_scale: 0.25` (82), `p_drop: 0.15` (50), `align_motif: True` (17), `sidechain_input: False` (117). INFERENCE: the checkpoint's embedded config can override model/diffuser keys (`assemble_config_from_chk`, A:model_runners.py:~186-198), so the values actually in effect for a given checkpoint are UNKNOWN. UNKNOWN: `fix_motif` and `symmetry` in effect.
- UNKNOWN: whether the already-noised `sample_init` output being re-diffused (3.3) and the mask polarity (3.4) reflect author intent.
- Out of scope and unasserted: any statement about hazardous-capability reduction, safety, or utility.

## 12. Source URLs

- https://github.com/audited-fork/safeRFdiffusion/commit/12d5426de27bc6411126262cf3f29bac3a0ce0c1
- https://github.com/audited-fork/safeRFdiffusion/commit/5cbd18a39c4607d65bdbf6457be3f79b27a6c3c1
- https://github.com/RosettaCommons/RFdiffusion/compare/e22092420281c644b928e64d490044dfca4f9175...audited-fork:main
