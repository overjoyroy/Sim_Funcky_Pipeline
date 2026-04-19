# Sim_Funcky_Pipeline

## What This Tool Does

Sim_Funcky_Pipeline preprocesses resting-state BOLD fMRI data and computes a functional connectivity similarity matrix. It follows the Power et al. 2014 recommendations for motion artifact removal. The pipeline is built with Nipype and delegates heavy lifting to FSL and ANTs.

**Primary outputs:**
- `final_preprocessed_output.nii.gz` — fully preprocessed 4D BOLD
- `sim_matrix.csv` — ROI × ROI Pearson correlation matrix (functional connectome)
- `average_arr.csv` — average BOLD signal per ROI per timeframe
- `aal2_trans.nii.gz` — AAL2 atlas warped into subject space
- `fd_dvars_plot.png` — motion metrics plot
- `rejections.json` — scrubbing summary (frames removed by FD/DVARS)

Results go to: `<outDir>/Sim_Funky_Pipeline/<subject_id>/func/<run_name>/`

---

## Pipeline Steps (in order)

1. **Reorient to standard** — FSL `fslreorient2std`
2. **Find best reference frame** — pairwise FLIRT similarity across all volumes; most representative volume used as motion correction target (skipped in `--testmode`, defaults to vol 0)
3. **Motion correction** — FSL MCFLIRT using best reference
4. **Brain extraction** — FSL BET on best reference frame, mask applied to full 4D BOLD
5. **Median-1000 normalization** — signal intensity normalized so median = 1000 (within brain mask)
6. **Framewise displacement (FD)** — FSL `fsl_motion_outliers`, threshold 0.5 mm
7. **Expand motion parameters** — 6 → 24 regressors (R, R², R', R'²)
8. **Head motion regression** — FSL GLM, outputs residuals
9. **Bandpass filtering** — FSL `fslmaths -bptf`, 0.009–0.08 Hz (sigma computed from TR)
10. **Spatial smoothing** — FSL, 6 mm FWHM
11. **DVARS** — custom implementation (threshold 5), flags outlier frames
12. **Scrubbing** — frames flagged by FD or DVARS are removed
13. **Merge** — cleaned 3D frames re-merged into 4D
14. **ANTs registration** — Affine + SyN; warps MNI152 template → subject space
15. **Atlas warp** — applies registration to AAL2 atlas in subject space
16. **Similarity matrix** — per-ROI average BOLD signal extracted, then Pearson correlation matrix computed (`pipeline_functions.py`)

---

## How to Run

### Dependencies
Requires FSL, ANTs, and the `infsci` conda environment:
```bash
conda activate infsci
```

### Direct (outside Docker)
The default template paths assume a Docker container (`/app/Template/`). When running locally, always pass `-tem` and `-seg` explicitly:

```bash
python3 Pipeline.py \
  -p /path/to/bids/data \
  -sid <subject_id> \
  -o /path/to/output \
  -tem /mnt/disk1/Research/Sim_Funcky_Pipeline/Template/MNI152lin_T1_4mm_brain.nii.gz \
  -seg /mnt/disk1/Research/Sim_Funcky_Pipeline/Template/aal2.nii.gz \
  --testmode
```

### Docker (recommended for portability)
```bash
docker build -t sim_funcky_pipeline .

docker run --rm -u $UID:$UID \
  -v /path/to/bids:/data/my_data \
  -v /path/to/output:/data/output \
  sim_funcky_pipeline \
  -p /data/my_data \
  -sid <subject_id> \
  -o /data/output
```

### All CLI flags

| Flag | Required | Description |
|------|----------|-------------|
| `-p` / `--parentDir` | Yes | BIDS dataset root |
| `-sid` / `--subject_id` | Yes | Subject ID (e.g. `0176_CNX_CHD_43`) |
| `-o` / `--outDir` | Yes | Output/derivatives directory |
| `-ses_id` / `--session_id` | No | Required if data has `ses-` subdirectories |
| `-tem` / `--template` | No | MNI template (default is Docker path `/app/Template/...`) |
| `-seg` / `--segment` | No | Atlas file (default is Docker path `/app/Template/...`) |
| `--saveIntermediates` | No | Save all intermediate files |
| `--testmode` | No | Fewer ANTs iterations + skips best-frame search; use for debugging |

### Expected BIDS input structure
```
data_dir/
└── <subject_id>/
    └── func/
        └── <subject_id>_..._bold.nii.gz
```
Files must end in `_bold.nii.gz` or `_bold.nii` to be detected.

---

## Key Files

- `Pipeline.py` — main workflow; defines all Nipype nodes and connections
- `pipeline_functions.py` — helper functions for similarity matrix computation (`make_average_arr`, `build_sim_arr`) and volume extraction (`getVolume`, `getSimilarityBetweenVolumes`)
- `Template/` — MNI152 templates and AAL2/AAL3 atlases
- `Template/sched.txt` — FSL schedule file used by best-frame finder

---

## Known Issues

TBD
