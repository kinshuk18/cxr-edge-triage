# Research and engineering rationale

## External validity and confounding

- **Zech et al., PLOS Medicine 15(11):e1002683, Nov 2018:** external-hospital performance was lower than internal in 3 of 5 comparisons; CNNs identified the hospital system with over 99.9% accuracy; a 10-fold prevalence difference helped internal results but did not generalize. Year is 2018 (the arXiv record's 2019 is wrong). Do NOT claim "text markers"; the evidence supports hospital-identity and prevalence confounding only.
- **Beede et al., CHI 2020:** field study at eleven clinics in Thailand. It is diabetic retinopathy (fundus), not radiology. Data-quality thresholds clashed with real clinic conditions. Lighting and network-drop specifics are unverified; mark them FLAG.
- **DeGrave, Janizek, Lee, Nature Machine Intelligence 2021;3:610-619:** COVID radiograph models use confounders; external testing alone is insufficient; explainability should precede deployment.
- **Oakden-Rayner et al., ACM CHIL 2020, pp.151-159:** hidden stratification, relative performance gaps over 20% on clinically important subsets. DROP the earlier chest-drain/pneumothorax claim; it is unsupported. Confirmed example is hip-fracture radiographs.
- **Adebayo et al., NeurIPS 2018, pp.9505-9515:** parameter-randomization sanity check. Gradients and Grad-CAM pass; Guided Backprop and Guided Grad-CAM fail. Design rule: plain Grad-CAM only, never Guided Grad-CAM.
- **WHO March 2021 consolidated TB guidelines, Module 2: Screening:** first recommendation of CAD for chest radiography interpretation. Cite Module 2, not Module 3. Age scope (15+) is unverified.
- **Deployment friction:** PATH Nagpur study with qXR (PLOS Digital Health, Dec 2023) lists installation, workflow integration, connectivity and staffing barriers. DICOM representation traps (MONOCHROME1 inversion, undecodable transfer syntax, bad window/rescale, burned-in PHI) come from engineering knowledge, not retrieved deployment logs. Label them that way.

## Why deterministic image handling comes first

A DICOM file is not simply a PNG in a wrapper. Stored samples may require a modality transform (`x = slope × stored + intercept`) before presentation transforms; windowing and VOI LUTs express a display view of the underlying pixel values. This implementation uses `pydicom.pixels.apply_voi_lut` on pydicom 3.x and falls back to the pydicom 2.x utility path. If a VOI LUT exists it is applied and normalized; otherwise the implementation uses the specified LINEAR, LINEAR_EXACT, or SIGMOID window equation when a valid width exists, or a p0.5–p99.5 fallback. `MONOCHROME1` inversion is deliberately performed after the VOI transform. Letterbox geometry is retained so the explanation map can be cropped from padding and resized back to the native row/column grid.

DICOM handling edge cases—MONOCHROME1 inversion, transfer syntaxes the host cannot decode, unreliable rescale/window metadata, and burned-in identifiers—are engineering risks derived from modality/format knowledge, not a measured incident dataset. The current code rejects decode failures and `BurnedInAnnotation=YES`, but does not inspect image pixels for burned-in PHI or solve every transfer-syntax/plugin dependency. **FLAG:** supported transfer syntaxes and a pixel-level burned-in-PHI screen must be validated against representative scanner exports.

## Monotone intensity transforms and training augmentation

A strictly increasing tone curve preserves the ordering of pixel intensities. Ideal global histogram equalization is rank/CDF based and therefore invariant to any strictly increasing tone remapping (up to finite-bin quantization and ties). CLAHE is the clipped, tile-local version of histogram equalization; its local histogram clipping limits contrast amplification, with the gain bounded by the configured clip factor. Gamma adjustment is a one-parameter family of monotone display curves and provides a useful approximation to a subset of scanner/display remappings.

The augmentation pipeline uses CLAHE, gamma and tone-curve perturbations alongside moderate brightness/contrast, blur/sharpen/downscale, noise, compression, affine transforms, elastic distortion and coarse dropout. These are training-only transformations; the inference path remains deterministic. No horizontal flips are used because left/right orientation is meaningful for chest radiographs. **FLAG:** the precise augmentations and parameter ranges are proposed engineering defaults and must be reviewed against held-out site data, diagnostic task, and scanner failure modes before any model training is relied upon.

Albumentations is pinned to 2.0.8, using constructor names for 2.x (`RandomResizedCrop(size=...)`, `GaussNoise(std_range=...)`, `ImageCompression(quality_range=...)`, and `CoarseDropout` range arguments). Albumentations 1.x uses different names and is not supported by this locked configuration.

## Explanation method

Grad-CAM is selected as the only local explanation implementation because the cited parameter-randomization sanity check reports that Grad-CAM and gradients pass, whereas Guided Backprop and Guided Grad-CAM fail. The activation map is ReLU-ed, maximum-normalized (all-zero when no positive evidence exists), and back-projected to native image coordinates. The overlay is a debugging/evidence artifact, not a proof of model correctness or a substitute for external validation.

## Calibration, OOD and hidden stratification

Temperature scaling is fitted offline with LBFGS over one log-temperature per class on held-out-site logits. This repository only contains a fitting utility; it does not include a dataset or fitted site calibration. The Mahalanobis gate operates on 1024-dimensional pooled DenseNet features and uses checkpoint-provided mean, precision, and score threshold. Its confidence thresholds and OOD threshold are checkpoint values; the random smoke checkpoint deliberately uses permissive thresholds and cannot establish useful behavior.

Mean confidence shifts can be tracked as an inexpensive screen, but mean-confidence drift is coarse and can miss subgroup failures or mix prevalence and case-mix changes. The monitoring alerts are operational signals, not clinical performance metrics. Hidden stratification motivates subgroup-level evaluation and careful external-site validation; a single aggregate score is not sufficient.

## Field deployment context and limits

The PATH Nagpur qXR study (PLOS Digital Health, Dec 2023) reports implementation barriers involving installation, workflow integration, connectivity and staffing. This codebase makes network delivery, queue state and retry semantics explicit, but the local infrastructure does not reproduce a clinic's workflow, scanner mix, power/network interruptions, staff workload, or governance environment. **FLAG:** lighting and network-drop details associated with the Beede study are not verified here and must not be stated as findings from that paper.

WHO reference scope for this research note is the March 2021 consolidated TB guidelines, **Module 2: Screening** and its first recommendation concerning CAD for chest-radiography interpretation. A minimum age claim (for example 15+) is unverified in this document and is intentionally not encoded as an eligibility policy.

## Evidence-based design decisions versus proposals

| Design choice | Evidence or status |
|---|---|
| Validate across sites and guard against hospital identity/prevalence shortcuts | Motivated by Zech et al. (2018) and DeGrave et al. (2021) |
| Evaluate hidden clinically important strata, not only aggregate metrics | Motivated by Oakden-Rayner et al. (2020); supported example is hip-fracture radiographs |
| Use plain Grad-CAM, not Guided Grad-CAM | Adebayo et al. (2018) parameter-randomization sanity checks |
| Use an explicit site calibration set and OOD abstention | Proposed engineering design; no trained checkpoint/calibration data ships here |
| The `qc_gate()` interface | **FLAG: unvalidated design proposal; default implementation always passes well-formed decoded images** |
| DICOM UID/date de-identification | **FLAG: incomplete; full PS3.15 Annex E handling is required** |
| Beede paper lighting/network-drop specifics | **FLAG: unverified; do not attribute to the paper** |
