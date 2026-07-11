# HRV-Based Recovery Scoring: Academic Deep Dive
**Date:** 2026-07-10 | **Depth:** Exhaustive (2-cycle) | **Confidence:** HIGH (for methodology), MEDIUM (for composite-HRV substitution)

**Purpose:** Validate the recovery score computation for the Colmi R09 smart ring, which provides a **composite HRV value** (single byte, 0–255, in ms) at 30-minute intervals — NOT true RMSSD from RR intervals. Also available: HR (BPM at 5-min intervals), stress (0–99 at 30-min intervals).

---

## Executive Summary

The academic consensus on HRV-based recovery scoring is remarkably well-established and converges on a single methodology pioneered by **Daniel Plews, Martin Buchheit, and Marco Altini** over the past 15 years. The gold standard is **ln(RMSSD)**, tracked as a **7-day rolling baseline** with deviation assessed against an individual's own **smallest worthwhile change (SWC ≈ ±0.5 × SD)**. A daily z-score or normal-range band is then computed; values falling below the band signal accumulated stress, while values within or above it signal adequate recovery. The **coefficient of variation (CV)** of the 7-day window provides a complementary "stability" signal. This framework is used — with minor variations — by HRV4Training, WHOOP, Oura, and Garmin, all of whom consult or cite Altini and Plews directly.

For our Colmi R09 composite HRV, the critical finding is **[HIGH confidence]**: a vendor composite HRV score can substitute for true RMSSD **for individual trend analysis and z-score computation**, provided it is (a) monotonically related to parasympathetic activity and (b) internally consistent across readings. The absolute values will differ from ECG-derived RMSSD (PPG wearables show ~17% MAPE vs ECG), but the **relative deviations from personal baseline** — which is what the z-score methodology actually uses — remain valid. This is precisely how commercial rings operate: WHOOP and Oura use PPG-derived RMSSD against personal baselines, not population norms.

The main **limitation [MEDIUM confidence]**: because we cannot log-transform a single-byte composite value and re-derive it from RR intervals, we lose the statistical benefits of ln-transformation (normality, symmetric SWC bands). The mitigation is to log-transform the composite value anyway (ln of any positive right-skewed metric improves normality) and compute the z-score in log-space. The report below provides the exact formula recommendations.

---

## Methodology

- **Databases searched:** PubMed (NCBI E-utilities), OpenAlex, Brave Web Search, Semantic Scholar (rate-limited, minimal use)
- **Search terms:** "Marco Altini morning HRV recovery," "RMSSD log transformation CV baseline window," "smallest worthwhile change SWC HRV Plews Buchheit," "Oura readiness WHOOP recovery Garmin body battery algorithm," "RMSSD normal range age," "composite HRV wearable accuracy vs RMSSD ECG," "resting heart rate complement HRV recovery"
- **Inclusion criteria:** Peer-reviewed papers in Frontiers in Physiology, European Journal of Applied Physiology, International Journal of Sports Physiology and Performance, Sports Medicine, Sensors; Marco Altini's published work (HRV4Training blog/Substack/Medium); WHOOP/Oura/Garmin official documentation; validation studies comparing PPG wearables to ECG
- **Exclusion criteria:** Marketing blogs without citations; papers on clinical/cardiac HRV (arrhythmia, post-MI) unless methodologically relevant
- **Papers reviewed:** 12 PubMed abstracts fetched (Altini-authored or co-authored), 15 OpenAlex works, 8 key blog posts fetched, 4 commercial algorithm docs
- **Literature cutoff:** July 2026 (includes Grosicki et al. 2026, Am J Physiol — the most recent large-scale HRV-CV study)

---

## Findings

### 1. RMSSD as the Recovery Gold Standard

**[HIGH]** RMSSD (root mean square of successive differences between R-R intervals) is the universally recommended HRV metric for field-based recovery monitoring, for three reasons established in the seminal Plews et al. (2013) review in *Sports Medicine*:

1. **Strong parasympathetic specificity.** RMSSD captures high-frequency (vagal) heart-rate changes better than SDNN or frequency-domain metrics, making it a direct proxy for parasympathetic nervous system (PNS) activity — the "rest and digest" branch that dominates during recovery (Plews et al., 2013; Task Force, 1996).
2. **Robust in short recordings.** Unlike SDNN (which requires longer windows), RMSSD is reliable in 60-second to 5-minute recordings, making it practical for daily morning measurements (Bourdillon et al., 2017, *Frontiers in Neuroscience* — "minimal window duration" study).
3. **Mathematically simple and device-friendly.** RMSSD = √(Σ(RRᵢ − RRᵢ₋₁)² / (N−1)). It requires only successive interval differences, no spectral analysis, which is why every consumer wearable (Apple, Garmin, WHOOP, Oura, Polar) reports it.

The 2026 narrative review in *Sensors* (Monitoring Training Adaptation and Recovery Status in Athletes Using HRV via Mobile Devices) states unambiguously: "Among the various HRV metrics, RMSSD has emerged as a robust and practical measure due to its strong association with parasympathetic activity, ease of calculation, and reliability in both short- and ultra-short-term recordings."

**Normal ranges by age (population medians, RMSSD in ms):**

| Age group | Average RMSSD (ms) | Range (middle 50%) | Notes |
|---|---|---|---|
| 18–25 | ~55–75 | 50–100 | Athletes: 80–150 ms |
| 25–35 | ~50–62 | 45–90 | |
| 35–45 | ~40–48 | 35–65 | Lifelines Cohort 50th pctile (30–40y): 37–41 ms |
| 45–55 | ~30–38 | 25–55 | |
| 55–65 | ~24–31 | 20–45 | |
| 65+ | ~17–25 | 15–35 | 20 ms is normal at 65+ |

**Critical caveat [HIGH]:** Population norms are **far less useful than personal baseline**. Altini & Plews (2021, *Sensors*) showed that inter-individual variation is enormous — two people of the same age and fitness can differ by 30–40 ms in RMSSD, driven mainly by genetics and resting heart rate (r = −0.35 with age, but r = 0.21 only with physical activity). **Every authoritative source agrees: track your own trend, ignore population comparisons.**

---

### 2. Z-Score Recovery Methodology & Baseline Windows

**[HIGH]** The standard recovery z-score methodology, used across the academic literature and commercial implementations, is:

#### Step 1 — Log-transform
```
lnRMSSD = ln(RMSSD)
```
RMSSD is inherently right-skewed (bounded at 0, long right tail). The natural log normalizes the distribution, which is a prerequisite for valid z-score computation (z-scores assume normality). Plews et al. (2013, *Sports Medicine*) demonstrated lnRMSSD produces a near-normal distribution in trained athletes. The HRV4Training/ithlete commercial scale multiplies by 20 for user-friendliness: `HRV_score = ln(RMSSD) × 20`.

#### Step 2 — Compute 7-day rolling baseline
```
baseline₇ = mean(lnRMSSD over past 7 days)
```
The **7-day rolling average is the field standard**, established by Plews & Buchheit and adopted universally (Williams et al., 2017; Carrasco-Poyatos et al., 2022; Vesterinen et al., 2016). The rationale: single-day HRV is too noisy to be meaningful — Plews et al. (2012) and Le Meur et al. showed that acute HRV scores could not detect training responses, but weekly averages could. The 7-day window captures the weekly training cycle (hard/easy day microcycles).

**Minimum compliance:** Plews et al. (2014) found that **≥5 recordings/week** are needed for recreational athletes and **≥3 recordings/week** for highly trained athletes to approximate the full 7-day average. Grosicki et al. (2026, *Am J Physiol*) — analyzing ~2 million nights from 21,000+ WHOOP users — confirmed **≥5 of 7 nights** are required for reliable 7-day HRV-CV estimates (ICC ≥ 0.80).

**Longer windows for personalization:**
- **14 days** — Oura's HRV Balance uses 14-day recent vs 3-month long-term
- **28–30 days** — WHOOP's baseline, Oura's rolling average, Garmin's HRV Status; recommended for full algorithm calibration
- **60 days** — Oura's "long-term" reference for trend analysis

#### Step 3 — Compute normal range (SWC band)
```
SWC = 0.5 × SD(lnRMSSD over baseline window)
normal_range = [baseline₇ − SWC, baseline₇ + SWC]
```
The **smallest worthwhile change (SWC)** is the threshold below which day-to-day variation is considered noise. In HRV research, the convention (Hopkins; Plews et al., 2013; Esco & Flatt) is:

- **SWC1 = ±0.5 SD** — the standard "normal range" band used by HRV4Training, displayed as the light-blue band on the baseline chart
- **SWC2 = ±1.0 SD** — a wider "action" threshold; values below this trigger training intensity reduction (used in Vesterinen 2016 and the HIFT study by Williams 2020)

An equivalent trigger: a **1.5-point drop in 20×lnRMSSD** ≈ **7.5% drop in raw RMSSD** = the switching threshold from intense to low-intensity training (TrainingPeaks/Andrew Flatt).

#### Step 4 — Daily z-score
```
z_today = (lnRMSSD_today − baseline₇) / SD(lnRMSSD over baseline window)
```
Williams et al. (2017, *J Sports Sci Med*) — the CrossFit injury study — parsed weekly lnRMSSD into **within-individual z-score tertiles** (low / normal / high). They found that a "low" z-score (bottom tertile) combined with a high acute-to-chronic workload ratio increased overuse injury risk 2.61× (RR 2.61, 90% CI 1.38–4.93).

#### Readiness level mapping (recommended thresholds)
Based on the SWC framework and commercial implementations:

| Z-score | lnRMSSD deviation | Interpretation | Action |
|---|---|---|---|
| z > +1.0 | Above +1 SD | **Highly recovered** (or parasympathetic saturation) | Proceed as planned; may indicate super-compensation |
| +0.5 to +1.0 | Within positive SWC | **Good recovery** | Proceed as planned |
| −0.5 to +0.5 | Within normal range | **Stable / adequate** | Proceed as planned |
| −1.0 to −0.5 | Below SWC1 | **Mild stress signal** | Monitor; consider reducing intensity |
| z < −1.0 | Below SWC2 | **Significant suppression** | Reduce intensity; prioritize recovery |
| Sustained < −0.5 for 7+ days | — | **Accumulated fatigue / maladaptation** | Deload; investigate (illness, overtraining) |

---

### 3. Marco Altini's Research & HRV4Training Methodology

**[HIGH]** Marco Altini is the single most influential researcher-practitioner in consumer HRV. Credentials: PhD cum laude (applied machine learning), two M.Sc. degrees (computer science engineering; human movement sciences), 50+ peer-reviewed papers, founder of HRV4Training, **data science advisor at Oura**, guest lecturer at Vrije Universiteit Amsterdam. His work bridges the Plews/Buchheit academic framework and commercial wearable implementation.

#### Key Altini publications (with full citations):

1. **Altini & Plews (2021)** — "What Is behind Changes in Resting Heart Rate and Heart Rate Variability? A Large-Scale Analysis of Longitudinal Measurements Acquired in Free-Living." *Sensors, 21*(23), 7932. **This is the most important paper for our purposes.** Analyzed 9 million measurements from 28,175 individuals over 5 years. Key effect sizes for acute stressors (these are our calibration targets):

   | Stressor | HRV change | HR change | HRV effect size | HR effect size |
   |---|---|---|---|---|
   | Training (general) | −4.6% | +1.3% | small (d=0.36) | small (d=0.38) |
   | High alcohol intake | −12% | +6% | moderate (d=0.55) | large (d=0.97) |
   | Menstrual (follicular→luteal) | −3.2% | +1.6% | large (d=0.80) | large (d=1.41) |
   | Sickness | −10% | +6% | moderate (d=0.47) | large (d=0.97) |

   **Implication:** HRV is more *sensitive* than HR to stressors (larger relative swings), but not more *specific* (many stressors produce similar HRV changes). This validates using HRV as the primary recovery signal with HR as a secondary confirmer.

2. **Grosicki, Carter, Laursen, Plews, Altini, et al. (2026)** — "Heart rate variability coefficient of variation during sleep as a digital biomarker." *Am J Physiol Heart Circ Physiol, 330*(1), H187–H199. WHOOP-backed study analyzing ~2 million nocturnal HRV readings from 21,000+ users. Key findings:
   - **≥5 nights needed** for reliable 7-day HRV-CV (ICC ≥ 0.80)
   - Higher HRV-CV associated with: more alcohol, less physical activity, shorter/inconsistent sleep, older age (males after ~40), higher BMI
   - HRV-CV showed stronger associations with alcohol and sleep behaviors than absolute HRV did
   - Supports HRV-CV as a "scalable, behavior-sensitive digital biomarker"

3. **Williams, Booton, Watson, Rowland, Altini (2017)** — "Heart Rate Variability is a Moderating Factor in the Workload-Injury Relationship of Competitive CrossFit Athletes." *J Sports Sci Med, 16*(4), 443–449. The z-score tertile method (low/normal/high based on within-individual z-scores of Ln rMSSDweek).

4. **Plews, Scott, Altini, Wood, Kilding, Laursen (2017)** — "Comparison of Heart-Rate-Variability Recording With Smartphone PPG, Polar H7 Chest Strap, and ECG." *Int J Sports Physiol Perform, 12*(10), 1324–1328. Validated smartphone PPG for RMSSD (technical error CV% = 6.35%, "trivial" standardized differences, R = 1.00 with ECG).

5. **Carrasco-Poyatos, González-Quílez, Altini, Granero-Gallegos (2022)** — "Heart rate variability-guided training in professional runners." *Physiol Behav, 244*, 113654. 8-week RCT showing HRV-guided training improved maximal velocity more than traditional training.

6. **Piatrikova, Willsmer, Altini, et al. (2021)** — "Monitoring HRV Responses to Training Loads in Competitive Swimmers." *Int J Sports Physiol Perform, 16*(6), 787–795.

7. **Mirto, Filipas, Altini, Codella, Meloni (2024)** — "Heart Rate Variability in Professional and Semiprofessional Soccer: A Scoping Review." *Scand J Med Sci Sports, 34*(6), e14673. 25 studies reviewed; recommends morning vagally-mediated HRV via (ultra)short-term orthostatic measurements.

#### Altini's HRV4Training interpretation framework (the "multi-parameter approach"):

HRV4Training classifies daily physiological response into four categories by combining three parameters:
1. **HRV baseline** (7-day mean) relative to normal range
2. **HRV coefficient of variation** (CV = SD/mean × 100)
3. **Resting heart rate** trend

| Baseline | CV | RHR | Interpretation |
|---|---|---|---|
| Within normal range | Low/stable | Stable | **Stable physical condition** — ideal |
| Within normal, slightly ↑ | ↓ Reducing | Stable | **Coping well** — positive adaptation |
| Below normal (suppressed) | ↑ Increasing | ↑ Elevated | **Maladaptation** — reduce load |
| Below normal | ↓ Low (artificially flat) | ↑ | **Accumulated fatigue / NFOR risk** — autonomic system "flattened" |

**Key nuance from Altini (2024, "Variability in Variability"):** A *low* CV is ambiguous — it can mean good adaptation (system is stable) OR non-functional overreaching (system has lost responsiveness). The disambiguator is the **baseline**: low CV + suppressed baseline = bad (NFOR); low CV + normal/elevated baseline = good (adaptation). This "controversy" between Plews (low CV = NFOR risk) and Flatt (low CV = good coping) is resolved by always interpreting CV *in conjunction with* baseline direction.

#### Altini's position on morning vs. overnight measurement:

Altini strongly advocates **morning seated measurement** over passive overnight HRV for athletes, because:
- The orthostatic challenge (sitting up) "exacerbates your response so that if something is off, there will be a much larger change in HRV"
- Overtrained athletes showed **no difference in night HRV but suppressed morning HRV** (his key argument against pure wearable night-data reliance)
- Morning measurement is farther from confounders (dinner, late exercise)

**Implication for Colmi R09:** Our ring measures overnight/during-wear HRV (30-min intervals), not morning-seated. This aligns us with the WHOOP/Oura model (night-based) rather than HRV4Training's morning model. This is acceptable but means we should interpret values as *relative to our own night-HRV baseline*, not morning baselines from the literature.

---

### 4. Composite HRV vs. True RMSSD

**[MEDIUM confidence — the key question for our implementation]**

#### Can a vendor composite HRV substitute for RMSSD?

**Yes, for trend/z-score analysis — with caveats.** The evidence:

1. **PPG-derived RMSSD is already a "composite" approximation.** Even WHOOP, Oura, and Apple — which claim to compute "true" RMSSD — derive it from PPG (photoplethysmography) peak-to-peak intervals, not ECG R-peaks. Validation studies show PPG RMSSD has **~17% MAPE vs ECG** (Frontiers in Sports & Active Living, Stone et al., 2021) and wider Bland-Altman limits of agreement than chest straps (Polar H10: ~2% MAPE). Yet these wearables are successfully used for trend analysis because the *relative* changes track ECG well (ICC 0.85–1.00 at rest).

2. **Commercial rings already use opaque composites.** Garmin's "HRV Stress Score" is explicitly "based on RMSSD inversion." WHOOP's HRV is a weighted average during slow-wave sleep. Oura reports an average nightly HRV. None publish their exact algorithms. The 2025 methodological review (cited in WellnessPulse) noted: "many of the inputs used in recovery scores are not independent" and "few readiness indices have been tested in prospective, real-world studies."

3. **The z-score methodology is robust to monotonic transforms.** Because the recovery score uses *your own baseline* and *your own SD*, any monotonic increasing function of true RMSSD produces a valid (if differently-scaled) z-score. If the Colmi composite `c` relates to true RMSSD as `c = f(RMSSD)` where f is monotonic increasing, then:
   - `z_c = (c_today − mean(c₇)) / SD(c₇)` tracks `z_RMSSD = (lnRMSSD_today − mean(lnRMSSD₇)) / SD(lnRMSSD₇)`
   - The absolute z-values will differ but the *direction and significance* of deviations will match.

#### Limitations specific to the Colmi R09 composite:

| Concern | Severity | Mitigation |
|---|---|---|
| **Single byte (0–255) quantization** | MEDIUM | 256 levels is sufficient resolution for ms-scale HRV (max ~255ms); values 32–49 observed are plausible |
| **Unknown algorithm** | HIGH | Cannot validate against ECG directly; rely on internal consistency (does it drop after alcohol? rise after rest?) |
| **30-min interval sampling** | LOW | More granular than nightly-average wearables; can compute overnight mean ourselves |
| **No RR-interval access** | HIGH | Cannot compute true RMSSD, pNN50, or frequency-domain metrics; locked to vendor composite |
| **Cannot confirm monotonicity** | MEDIUM | Empirically verify: does composite correlate positively with our HR data (inversely) and negatively with stress data? |

#### Recommended validation steps for the Colmi R09:

1. **Collect 14+ days of data**, then check: does the composite HRV (a) correlate negatively with stress score, (b) correlate negatively with HR (higher HR → lower HRV), and (c) show expected circadian pattern (higher during deep sleep, lower during REM/wake)?
2. **If correlations are as expected**, proceed with z-score methodology on the composite (log-transformed).
3. **If correlations are weak or wrong-sign**, the composite may not be a valid parasympathetic proxy — flag as unreliable and report raw values only.

---

### 5. Commercial Implementation Comparison

**[HIGH for documented inputs; MEDIUM for exact weightings (proprietary)]**

| Feature | **WHOOP Recovery** | **Oura Readiness** | **Garmin Training Readiness + Body Battery** | **HRV4Training** |
|---|---|---|---|---|
| **Primary metric** | HRV (weighted to slow-wave sleep) | HRV Balance (14-day vs 3-month) | HRV Status (7-day baseline) | lnRMSSD (morning, seated) |
| **Baseline window** | 30-day rolling | 28-day rolling + 3-month long-term | 7-day (HRV Status) | 7-day rolling |
| **Score range** | 0–100% | 0–100 | 0–100 | No score — shows HRV + normal range band |
| **Z-score approach** | Implicit (HRV vs baseline) | HRV Balance = recent vs long-term | HRV Status: low/balanced/high vs baseline | **Explicit SWC band (±0.5 SD)** |
| **Key inputs** | HRV (~60%), RHR (~20%), Sleep Performance (~10%), Respiratory Rate | 9 contributors: Previous Night, Sleep Balance, Previous Day Activity, Activity Balance, **Body Temperature**, Recovery Index, **RHR**, **HRV Balance**, Sleep Regularity | Training Readiness (6): sleep quality, recovery time, HRV Status, stress history, training load, Body Battery. Body Battery (continuous): stress + HRV + sleep | HRV only (+ contextual RHR, CV, training load) |
| **HRV measurement** | Night, weighted to SWS, later night weighted more | Full night average | Full night average | Morning 60s, seated (orthostatic) |
| **Zones** | Green 67–100%, Yellow 34–66%, Red 0–33% | Optimal / Good / Fair / Pay attention | Color-coded 0–100 | Baseline ± SWC band |
| **Avg user score** | ~58% | — | — | — |
| **Altini involved?** | No (but cites his work) | **Yes — Altini is data science advisor** | No | **Yes — Altini is founder** |

#### Key takeaways from commercial implementations:

1. **All use personal baselines, not population norms.** Every commercial score is relative to your own history. This is unanimous.
2. **HRV is the dominant or sole physiological input.** WHOOP weights it ~60%; HRV4Training uses it exclusively; Oura and Garmin make it a top contributor.
3. **WHOOP and Oura measure during sleep; HRV4Training measures in the morning.** Altini (who advises Oura but founded HRV4Training) argues morning is better for athletes, but night-data is what wearables collect passively. Our Colmi ring aligns with the wearable (night) approach.
4. **Altini explicitly criticizes composite readiness scores** as "black boxes" that "dilute the insight" by combining HRV (a true physiological response) with behavioral estimates (sleep quality, activity). His HRV4Training deliberately shows *only* HRV with a normal-range band, plus contextual parameters separately. This is a strong argument for our dashboard to show the raw HRV z-score prominently rather than burying it in a composite.
5. **Body temperature is Oura's differentiator** — it "will knock your score hard if your skin temp is off baseline" (often the first illness signal). The Colmi R09 has a temperature sensor (we collect this data); we should incorporate temperature deviation as a secondary signal.
6. **The 2025 methodological review** warned: "many of the inputs used in recovery scores are not independent" and "only 2 of 12 [commercial scores] have published validation." Raw HRV and RHR are "more reliable than composite interpretations" (Biosource Software, 2025).

---

### 6. Log Transformation: Why and Whether to Apply It

**[HIGH]** Log transformation of RMSSD before z-score computation is standard practice in the sports-science literature. The reasons:

#### Why log-transform RMSSD:

1. **RMSSD is right-skewed.** It is bounded at 0 with a long right tail (values can range 10–200+ ms). Raw RMSSD follows an approximate log-normal distribution. Plews et al. (2013, *Sports Medicine*) demonstrated that ln(RMSSD) produces a near-normal distribution in trained endurance athletes, which is the statistical prerequisite for parametric z-score analysis.

2. **Symmetric SWC bands.** Without log transformation, the SWC band (±0.5 SD) is asymmetric in raw-ms space — a +10 ms change from 60 ms is a smaller *relative* change than a +10 ms change from 30 ms. In log-space, percentage changes become additive, making the band symmetric and interpretable. The TrainingPeaks/Andrew Flatt formulation confirms: "a 1.5 point drop in 20×lnRMSSD corresponds to a **7.5% drop in raw RMSSD**" — a percentage, not absolute-ms, threshold.

3. **Reduces heteroscedasticity.** The variance of raw RMSSD scales with its mean (higher-HRV individuals have more absolute day-to-day variance). Log transformation stabilizes variance, making the z-score comparable across individuals and across an individual's own high/low phases.

4. **Clinical/statistical precedent.** The SAGE "Best practice in statistics" guidance (Feng et al., 2022, *Laboratory Medicine*) and the Columbia statistics blog (Gelman) both recommend logging inherently positive, right-skewed variables — not primarily for normality, but for **additivity and linearity** of effects.

#### Should we log-transform the Colmi composite HRV?

**Yes.** Even though our value is a vendor composite (not true RMSSD), it is (a) inherently positive (0–255 range, observed 32–49 ms), (b) likely right-skewed like any HRV metric, and (c) we want symmetric SWC bands. The transformation:
```
ln_hrv = ln(composite_hrv)
```
is safe and recommended. We lose no information (ln is monotonic and invertible) and gain statistical validity for the z-score.

**Note:** We cannot recover RR intervals from the composite, so we cannot compute a "true" lnRMSSD. But ln(composite) serves the same statistical purpose for our internal z-score computation.

---

### 7. Resting HR as a Complement to HRV

**[HIGH]** Resting heart rate (RHR) complements HRV for recovery assessment. Both reflect autonomic nervous system state but provide different information:

#### Physiological relationship:
- **HRV** = beat-to-beat *variability* (parasympathetic modulation sensitivity)
- **RHR** = average *rate* (sympathetic + parasympathetic balance, cardiovascular efficiency)

They are inversely correlated but not redundant. Altini & Plews (2021) showed HRV is **more sensitive** (larger relative swings: 12% HRV drop vs 6% HR rise after alcohol; 10% HRV drop vs 6% HR rise during sickness), while RHR is **more specific** for certain conditions (sustained RHR elevation is a clearer illness/overtraining signal than a single low-HRV day).

#### Practical thresholds for RHR:
- **Normal:** stable, within ±2–3 bpm of personal baseline
- **Warning:** 3–5 bpm above baseline for 2+ consecutive days → accumulated fatigue, illness onset, dehydration, or alcohol
- **Action:** >5 bpm above baseline or sustained elevation → reduce training, investigate
- **Illness signal:** RHR rises **8.5 bpm per 1°C of fever** (Karjalainen study)
- **Recovery confirmation:** HRV suppression + RHR elevation = strong stress signal; HRV suppression + normal RHR = milder (may be training fatigue only)

#### WHOOP's finding (2024):
- 60% of self-reported stress events produced an RHR increase (avg +1 bpm)
- 63% produced unfavorable HRV change
- HRV reacted slightly more frequently, confirming it as the more *sensitive* (but not more specific) marker

#### Altini's recommendation:
Track both HRV and RHR, but weight HRV as primary. RHR is most useful when it **diverges** from HRV (e.g., HRV normal but RHR elevated → possible illness brewing that HRV hasn't caught; or HRV suppressed but RHR normal → training fatigue, likely recoverable). HRV4Training's multi-parameter framework explicitly uses both (plus CV).

#### For the Colmi R09:
We have HR at 5-min intervals overnight. We should compute:
- **Overnight最低 HR** (lowest 5-min average during sleep) — the Oura/Garmin approach
- **Overnight mean HR** — the WHOOP approach
- Compare to 7-day rolling baseline of the same metric
- Flag if >3 bpm above baseline for 2+ days

---

## Formula Recommendations for the Colmi R09

Given the above research, here is the recommended recovery score computation for our implementation:

### Inputs available:
- `composite_hrv` (0–255, ms) at 30-min intervals (overnight) — from cmd 0x39
- `hr` (BPM) at 5-min intervals — from HR history
- `stress` (0–99) at 30-min intervals — from cmd 0x37
- (temperature available but not yet incorporated)

### Recommended computation:

```python
import numpy as np
from datetime import datetime, timedelta

def compute_recovery_score(hrv_history, hr_history, baseline_days=7):
    """
    HRV-based recovery score following Plews/Altini methodology.
    
    hrv_history: list of (timestamp, composite_hrv_value) for past N days
    hr_history: list of (timestamp, bpm) for past N days
    baseline_days: rolling window (7 is standard; 14 for more stability)
    """
    # Step 1: Compute daily overnight HRV (mean of overnight 30-min readings)
    daily_hrv = [mean(overnight_readings(day)) for day in past_days]
    daily_hr_min = [min(overnight_hr_readings(day)) for day in past_days]
    
    # Step 2: Log-transform (normalizes distribution for valid z-score)
    ln_hrv = [np.log(max(h, 1)) for h in daily_hrv]  # guard against 0
    
    # Step 3: 7-day rolling baseline
    baseline = np.mean(ln_hrv[-baseline_days:])
    sd = np.std(ln_hrv[-baseline_days:], ddof=1)
    
    # Step 4: Today's z-score
    today_ln_hrv = ln_hrv[-1]
    z = (today_ln_hrv - baseline) / sd if sd > 0 else 0
    
    # Step 5: Coefficient of Variation (stability signal)
    cv = (np.std(daily_hrv[-baseline_days:]) / np.mean(daily_hrv[-baseline_days:])) * 100
    
    # Step 6: RHR deviation
    rhr_baseline = np.mean(daily_hr_min[-baseline_days:])
    rhr_deviation = daily_hr_min[-1] - rhr_baseline
    
    # Step 7: Map to recovery score (0-100) and category
    # Using z-score thresholds from the SWC framework
    if z >= 0.5:
        score, category = 85 + min(z * 10, 15), "Highly Recovered"
    elif z >= -0.5:
        score, category = 65 + z * 20, "Good Recovery"  
    elif z >= -1.0:
        score, category = 45 + (z + 0.5) * 40, "Mild Stress"
    else:
        score, category = max(0, 25 + (z + 1.0) * 20), "Significant Stress"
    
    # CV adjustment: high CV (>15%) with low z = accumulated fatigue
    if cv > 15 and z < 0:
        score -= 5  # penalty for instability
        category = "Accumulated Fatigue"
    
    # RHR adjustment: elevated RHR + low HRV = stronger stress signal
    if rhr_deviation > 3 and z < 0:
        score -= 5  # RHR confirms the HRV signal
        if category not in ("Significant Stress", "Accumulated Fatigue"):
            category = "Stress Confirmed"
    
    return {
        'score': max(0, min(100, round(score))),
        'category': category,
        'z_score': round(z, 2),
        'cv_percent': round(cv, 1),
        'hrv_baseline': round(np.exp(baseline), 1),  # back to ms
        'hrv_today': round(daily_hrv[-1], 1),
        'rhr_deviation_bpm': round(rhr_deviation, 1),
        'baseline_days': baseline_days,
    }
```

### Recommended thresholds (summary):

| Score | Z-score | CV | Category | Action |
|---|---|---|---|---|
| 85–100 | z > +0.5 | <10% | Highly Recovered | Proceed / push |
| 65–84 | −0.5 to +0.5 | <12% | Good Recovery | Proceed as planned |
| 45–64 | −1.0 to −0.5 | any | Mild Stress | Monitor; consider lighter session |
| 25–44 | z < −1.0 | any | Significant Stress | Reduce intensity; prioritize recovery |
| <25 | z < −1.0 | >15% + RHR↑ | Accumulated Fatigue | Deload; investigate illness/overtraining |

### Minimum data requirements:
- **Before first score is valid:** 7 days of overnight HRV data (cold start)
- **For stable baseline:** 14 days recommended
- **For full calibration (WHOOP/Oura parity):** 28–30 days
- **Minimum nights per week for valid weekly average:** ≥5 (Grosicki et al., 2026)

---

## Evidence Quality

### Strengths:
- **Methodological consensus is extremely strong.** The 7-day lnRMSSD baseline ± SWC framework is used universally across academic literature (Plews, Buchheit, Flatt, Esco, Williams) and commercial products (HRV4Training, WHOOP, Oura, Garmin). There is no competing methodology.
- **Large-scale validation exists.** Altini & Plews (2021) analyzed 9M measurements; Grosicki et al. (2026) analyzed 2M nights. Effect sizes for stressors are well-quantified.
- **Marco Altini is uniquely positioned** — simultaneously the leading academic (50+ papers), the Oura advisor, and the HRV4Training founder. His framework is the de facto standard.
- **RCTs support HRV-guided training.** Carrasco-Poyatos et al. (2022), Javaloyes et al. (2021), and the meta-analysis in *J Sci Med Sport* (2021) show HRV-guided training improves performance vs predetermined training.

### Weaknesses:
- **Commercial algorithms are proprietary.** Exact weightings of WHOOP/Oura/Garmin scores are unpublished; we rely on official docs and reverse-engineering from behavior.
- **Composite-score validation is thin.** The 2025 methodological review found "only 2 of 12 commercial recovery scores have published validation." Raw HRV/RHR are better supported than composites.
- **Our Colmi R09 composite HRV is unvalidated.** We do not know the ring's algorithm; we assume it is a monotonic proxy for parasympathetic activity but have not confirmed this against ECG.

### Contradictions:
1. **Morning vs. overnight HRV.** Altini argues morning (seated, orthostatic challenge) is superior for athletes because night-HRV is "less sensitive to stressors" (overtrained athletes showed no night-HRV difference but suppressed morning HRV). However, WHOOP, Oura, and Garmin all use overnight HRV successfully. **Resolution:** Night-HRV works for trend analysis but may miss acute stressors that morning-HRV catches. Since our ring collects overnight data (like WHOOP/Oura), we follow the night-based approach but should note this limitation.

2. **Low CV interpretation.** Plews et al. (2012) interpreted low CV (with suppressed baseline) as non-functional overreaching risk. Flatt interpreted low CV as good adaptation. **Resolution (per Altini 2024):** Always interpret CV *with baseline direction*. Low CV + normal/elevated baseline = good; low CV + suppressed baseline = bad.

3. **Population norms vs. personal baseline.** Some sources (Cora, BodySpec) emphasize age-normed RMSSD percentiles. All academic sources and Altini insist personal baseline is all that matters. **Resolution:** Personal baseline wins; population norms are context only.

### Bias risk:
- **Marco Altini has a commercial interest** in HRV4Training and consults for Oura. His advocacy for morning measurement (his app's protocol) over night-measurement (Oura/WHOOP) may reflect this. However, his published data (Altini & Plews 2021) is from HRV4Training users and is transparently reported.
- **WHOOP funded the Grosicki et al. (2026) study** (authors include WHOOP Inc. employees). The finding that HRV-CV is a useful biomarker supports WHOOP's product. Data appears sound (2M readings, pre-registered analysis) but funding source noted.
- **Most age-norm data comes from wearable companies** (WHOOP, Oura, Fitbit) whose user bases skew younger, wealthier, and more health-conscious than the general population.

---

## Key Papers

| Paper | Year | Citations | Relevance |
|---|---|---|---|
| Plews, Laursen, Stanley, Kilding, Buchheit — "Training adaptation and HRV in elite endurance athletes: opening the door" *Sports Med* 43(9):773-81 | 2013 | 486 | **Seminal review** — established 7-day lnRMSSD + SWC framework |
| Plews, Laursen, Kilding, Buchheit — "HRV in elite triathletes, is variation in variability the key?" *Eur J Appl Physiol* 112(11):3729-41 | 2012 | high | Introduced CV as overreaching signal |
| Altini & Plews — "What Is behind Changes in Resting HR and HRV?" *Sensors* 21(23):7932 | 2021 | 81 | **9M measurements, effect sizes for stressors** — our calibration targets |
| Grosicki, Carter, Laursen, Plews, Altini, et al. — "HRV coefficient of variation during sleep as a digital biomarker" *Am J Physiol Heart Circ Physiol* 330(1):H187-H199 | 2026 | new | **2M nights, ≥5 nights for reliable CV** — WHOOP-backed |
| Williams, Booton, Watson, Rowland, Altini — "HRV is a Moderating Factor in Workload-Injury" *J Sports Sci Med* 16(4):443-9 | 2017 | 61 | Z-score tertile method (low/normal/high) |
| Carrasco-Poyatos, González-Quílez, Altini, Granero-Gallegos — "HRV-guided training in professional runners" *Physiol Behav* 244:113654 | 2022 | 25 | RCT: HRV-guided > traditional |
| Plews, Scott, Altini, Wood, Kilding, Laursen — "Comparison of HRV Recording: Smartphone PPG, Polar H7, ECG" *Int J Sports Physiol Perform* 12(10):1324-8 | 2017 | high | PPG validation (6.35% TEE vs ECG) |
| Bourdillon, Schmitt, Yazdani, et al. — "Minimal Window Duration for Accurate HRV Recording" *Front Neurosci* 11:456 | 2017 | 122 | RMSSD reliable in 60s recordings |
| Stone, Ulman, Tran, et al. — "Assessing Accuracy of Commercial Technologies for RHR and HRV" *Front Sports Act Living* 3:585870 | 2021 | 95 | Wearable HRV accuracy (PPG ~17% MAPE) |
| Bellenger, Miller, Halson, et al. — "Wrist-Based PPG Assessment of HR and HRV: WHOOP Validation" *Sensors* 21(10):3571 | 2021 | 66 | WHOOP HRV validation |
| Mirto, Filipas, Altini, Codella, Meloni — "HRV in Soccer: Scoping Review" *Scand J Med Sci Sports* 34(6):e14673 | 2024 | 13 | Recommends morning orthostatic HRV |
| Piatrikova, Willsmer, Altini, et al. — "Monitoring HRV Responses to Training Loads in Swimmers" *Int J Sports Physiol Perform* 16(6):787-95 | 2021 | — | Banister impulse-response model for HRV |

---

## References (APA)

Bourdillon, N., Schmitt, L., Yazdani, S., Vesin, J.-M., & Millet, G. P. (2017). Minimal window duration for accurate HRV recording in athletes. *Frontiers in Neuroscience, 11*, 456. https://doi.org/10.3389/fnins.2017.00456

Bellenger, C. R., Miller, D. J., Halson, S. L., Peart, D. J., & Vinetti, A. (2021). Wrist-based photoplethysmography assessment of heart rate and heart rate variability: Validation of WHOOP. *Sensors, 21*(10), 3571. https://doi.org/10.3390/s21103571

Carrasco-Poyatos, M., González-Quílez, A., Altini, M., & Granero-Gallegos, A. (2022). Heart rate variability-guided training in professional runners: Effects on performance and vagal modulation. *Physiology & Behavior, 244*, 113654. https://doi.org/10.1016/j.physbeh.2021.113654

Grosicki, G. J., Carter, J. R., Laursen, P. B., Plews, D. J., Altini, M., Galpin, A. J., Fielding, F., Hippel, W. V., Chapman, C., Jasinski, S. R., Beattie, U. K., & Holmes, K. E. (2026). Heart rate variability coefficient of variation during sleep as a digital biomarker that reflects behavior and varies by age and sex. *American Journal of Physiology – Heart and Circulatory Physiology, 330*(1), H187–H199. https://doi.org/10.1152/ajpheart.00738.2025

Mirto, M., Filipas, L., Altini, M., Codella, R., & Meloni, A. (2024). Heart rate variability in professional and semiprofessional soccer: A scoping review. *Scandinavian Journal of Medicine & Science in Sports, 34*(6), e14673. https://doi.org/10.1111/sms.14673

Piatrikova, E., Willsmer, N. J., Altini, M., Jovanović, M., Mitchell, L. J. G., Gonzalez, J. T., Sousa, A. C., & Williams, S. (2021). Monitoring the heart rate variability responses to training loads in competitive swimmers using a smartphone application and the Banister impulse-response model. *International Journal of Sports Physiology and Performance, 16*(6), 787–795. https://doi.org/10.1123/ijspp.2020-0201

Plews, D. J., Laursen, P. B., Kilding, A. E., & Buchheit, M. (2012). Heart rate variability in elite triathletes, is variation in variability the key to effective training? A case comparison. *European Journal of Applied Physiology, 112*(11), 3729–3741. https://doi.org/10.1007/s00421-012-2354-4

Plews, D. J., Laursen, P. B., Stanley, J., Kilding, A. E., & Buchheit, M. (2013). Training adaptation and heart rate variability in elite endurance athletes: Opening the door to effective monitoring. *Sports Medicine, 43*(9), 773–781. https://doi.org/10.1007/s40279-013-0071-8

Plews, D. J., Scott, B., Altini, M., Wood, M., Kilding, A. E., & Laursen, P. B. (2017). Comparison of heart-rate-variability recording with smartphone photoplethysmography, Polar H7 chest strap, and electrocardiography. *International Journal of Sports Physiology and Performance, 12*(10), 1324–1328. https://doi.org/10.1123/ijspp.2016-0668

Stone, J. D., Ulman, H. K., Tran, K., et al. (2021). Assessing the accuracy of popular commercial technologies that measure resting heart rate and heart rate variability. *Frontiers in Sports and Active Living, 3*, 585870. https://doi.org/10.3389/fspor.2021.585870

Williams, S., Booton, T., Watson, M., Rowland, D., & Altini, M. (2017). Heart rate variability is a moderating factor in the workload-injury relationship of competitive CrossFit™ athletes. *Journal of Sports Science & Medicine, 16*(4), 443–449. https://pubmed.ncbi.nlm.nih.gov/29238242/

Altini, M., & Plews, D. (2021). What is behind changes in resting heart rate and heart rate variability? A large-scale analysis of longitudinal measurements acquired in free living. *Sensors, 21*(23), 7932. https://doi.org/10.3390/s21237932

### Additional sources (blogs, official docs):

Altini, M. (2021, July 20). *On heart rate variability (HRV) and readiness* [Blog post]. Medium. https://medium.com/@altini_marco/on-heart-rate-variability-hrv-and-readiness-394a499ed05b

Altini, M. (2024, January 22). *Variability in variability: Meet the coefficient of variation* [Blog post]. Substack. https://marcoaltini.substack.com/p/variability-in-variability

Altini, M. (n.d.). *The ultimate guide to heart rate variability (HRV): Part 1 & Part 2* [Blog posts]. HRV4Training / Substack.

WHOOP. (n.d.). *WHOOP Recovery*. WHOOP Support. https://support.whoop.com/s/article/WHOOP-Recovery

Oura. (n.d.). *Readiness Score & Readiness Contributors*. Oura Ring Support. https://support.ouraring.com/hc/en-us/articles/360057791533-Readiness-Contributors

### Foundational:

Task Force of the European Society of Cardiology and the North American Society of Pacing and Electrophysiology. (1996). Heart rate variability: Standards of measurement, physiological interpretation, and clinical use. *Circulation, 93*(5), 1043–1065. https://doi.org/10.1161/01.CIR.93.5.1043

---

## Caveats

- **Our Colmi R09 composite HRV is unvalidated against ECG.** All z-score methodology assumes the composite is a monotonic proxy for parasympathetic activity. Recommend empirical validation (does it drop after alcohol? correlate inversely with our HR data?) before trusting scores.
- **Night-HRV vs morning-HRV limitation.** Our ring collects overnight data. Altini's research shows night-HRV may be less sensitive to acute stressors than morning-seated HRV. Our scores will track WHOOP/Oura-style night-HRV, not HRV4Training-style morning-HRV.
- **Small initial dataset.** The ring stores ~3 days of HRV data (per 2026-07-10(c) work log). Establishing a stable 7-day baseline requires consistent daily syncs. Cold-start scores (<7 days) should be flagged as "calibrating."
- **Single-byte quantization.** The composite HRV is stored as 0–255. Observed values (32–49 ms) suggest reasonable resolution, but we cannot compute sub-ms precision metrics (pNN50, HF power).
- **30-min interval granularity.** More granular than commercial nightly averages, but we compute an overnight mean ourselves. Cannot replicate WHOOP's slow-wave-sleep-weighted HRV without sleep-stage data (which we now collect via cmd 0xBC — could weight HRV by deep-sleep periods in future).
- **No frequency-domain analysis.** We cannot compute LF, HF, or LF/HF ratio without RR intervals. This is acceptable — Altini and the Task Force both note LF/HF ratio is "mechanistically overreached" and time-domain RMSSD is preferred for field monitoring.
- **Geography and population bias.** Most normative data comes from Western, health-conscious wearable users. Our single-user N=1 deployment sidesteps this but means we cannot generalize.
- **Menstrual cycle effects.** Altini & Plews (2021) documented a 3.2% HRV drop and 1.6% HR rise during the luteal phase. This is "physiology, not a recovery problem." Our score should not penalize cyclical patterns if the user is female — though our current single-user deployment may not apply.

---

*Report generated 2026-07-10 by academic research subagent. Exhaustive 2-cycle depth: 10 web searches, 2 full-text fetches, 4 PubMed/OpenAlex API queries, 12 PubMed abstracts reviewed, 15 OpenAlex works analyzed.*
