# Agentic View Classification Guideline Summary

This local summary is for research decision-support development. It must be used with rendered image evidence, DICOM metadata, calibration provenance, uncertainty, and privacy constraints.

## Local Sources
- `2013_Performing-Comprehensive-TEE.pdf`: pdf_text, 216379 extracted characters
- `2017VavularRegurgitationGuideline.pdf`: pdf_text, 312255 extracted characters
- `Guidelines-for-Performing-a-Comprehensive-Transthoracic-Echocardiographic-Examination-in-Adults.pdf`: pdf_text, 202846 extracted characters

## View Criteria
### PLAX
- parasternal long-axis geometry
- left ventricle long axis
- aortic root and aortic valve
- mitral valve and left atrium
- anterior and posterior wall orientation
- Measurement suitability: Useful for aortic root, LVOT, aortic valve, color jet context, and vena contracta when calibrated.

### PSAX
- parasternal short-axis geometry
- circular ventricular or valve-level cross section
- aortic valve short-axis or LV short-axis level
- papillary muscle or mitral valve short-axis anatomy
- Measurement suitability: Useful for valve-level morphology and jet origin context; not a substitute for calibrated volumetric measurements.

### A4C
- apical four-chamber geometry
- left and right ventricles visible
- left and right atria visible
- mitral and tricuspid valve plane
- apex near image sector origin
- Measurement suitability: Useful for chamber context, color Doppler, and PWD/CWD alignment when acquisition geometry supports it.

### A2C
- apical two-chamber geometry
- left ventricle and left atrium
- mitral valve without right-sided chambers
- apex-to-base long-axis alignment
- Measurement suitability: Useful for LV biplane support and apical color/spectral context.

### A3C
- apical long-axis geometry
- left ventricle, left atrium, mitral valve, and aortic valve
- LV outflow tract and aortic root from apical window
- Measurement suitability: Useful for LVOT/aortic valve alignment and AR CWD/color evidence.

### suprasternal
- suprasternal notch window
- aortic arch and great vessel orientation
- descending thoracic aorta continuity
- Measurement suitability: Useful for aortic arch and descending aortic flow reversal evidence when sample site is known.

### subcostal
- subcostal window
- liver-proximal acoustic window
- inferior vena cava or abdominal aorta context
- horizontal four-chamber orientation may be present
- Measurement suitability: Useful for alternative chamber/aortic context and abdominal aortic PWD reversal evidence when sample site is known.

## Limitations And Safety Notes
- These criteria support view and modality orientation only; they do not establish clinical severity.
- Missing calibration, unreadable rendered media, or absent provenance is an engineering/tooling defect to repair.
- Preserve discordant evidence and uncertainty; do not average contradictory sources into a single opaque label.

## Rendered Guideline Pages For Agent Review
Use these local page-render artifacts as visual guideline context. They are not patient data.
- `2013_Performing-Comprehensive-TEE_page_002.png` from `2013_Performing-Comprehensive-TEE.pdf` page 2 (matched: long-axis, short-axis, M-mode)
- `2013_Performing-Comprehensive-TEE_page_004.png` from `2013_Performing-Comprehensive-TEE.pdf` page 4 (matched: Doppler)
- `2013_Performing-Comprehensive-TEE_page_005.png` from `2013_Performing-Comprehensive-TEE.pdf` page 5 (matched: Doppler)
- `2013_Performing-Comprehensive-TEE_page_009.png` from `2013_Performing-Comprehensive-TEE.pdf` page 9 (matched: color)
- `2013_Performing-Comprehensive-TEE_page_012.png` from `2013_Performing-Comprehensive-TEE.pdf` page 12 (matched: four-chamber, Doppler, color)
- `2013_Performing-Comprehensive-TEE_page_013.png` from `2013_Performing-Comprehensive-TEE.pdf` page 13 (matched: four-chamber, long-axis, Doppler, color)
- `2017VavularRegurgitationGuideline_page_001.png` from `2017VavularRegurgitationGuideline.pdf` page 1 (matched: Doppler, color)
- `2017VavularRegurgitationGuideline_page_002.png` from `2017VavularRegurgitationGuideline.pdf` page 2 (matched: short-axis, Doppler, color)
- `2017VavularRegurgitationGuideline_page_003.png` from `2017VavularRegurgitationGuideline.pdf` page 3 (matched: Doppler, color)
- `2017VavularRegurgitationGuideline_page_004.png` from `2017VavularRegurgitationGuideline.pdf` page 4 (matched: Doppler, M-mode, color)
- `2017VavularRegurgitationGuideline_page_005.png` from `2017VavularRegurgitationGuideline.pdf` page 5 (matched: Doppler, color)
- `2017VavularRegurgitationGuideline_page_006.png` from `2017VavularRegurgitationGuideline.pdf` page 6 (matched: Doppler, color)
- `Guidelines-for-Performing-a-Comprehensive-Transthoracic-Echocardiographic-Examination-in-Adults_page_001.png` from `Guidelines-for-Performing-a-Comprehensive-Transthoracic-Echocardiographic-Examination-in-Adults.pdf` page 1 (matched: Doppler, color)
- `Guidelines-for-Performing-a-Comprehensive-Transthoracic-Echocardiographic-Examination-in-Adults_page_002.png` from `Guidelines-for-Performing-a-Comprehensive-Transthoracic-Echocardiographic-Examination-in-Adults.pdf` page 2 (matched: parasternal, apical, four-chamber, two-chamber, long-axis, short-axis, suprasternal, subcostal, Doppler, color, zoom)
- `Guidelines-for-Performing-a-Comprehensive-Transthoracic-Echocardiographic-Examination-in-Adults_page_003.png` from `Guidelines-for-Performing-a-Comprehensive-Transthoracic-Echocardiographic-Examination-in-Adults.pdf` page 3 (matched: parasternal, apical, four-chamber, two-chamber, long-axis, short-axis, Doppler, M-mode, color)
- `Guidelines-for-Performing-a-Comprehensive-Transthoracic-Echocardiographic-Examination-in-Adults_page_004.png` from `Guidelines-for-Performing-a-Comprehensive-Transthoracic-Echocardiographic-Examination-in-Adults.pdf` page 4 (matched: parasternal, apical, four-chamber, long-axis, short-axis, suprasternal, subcostal, Doppler, M-mode, color)
- `Guidelines-for-Performing-a-Comprehensive-Transthoracic-Echocardiographic-Examination-in-Adults_page_005.png` from `Guidelines-for-Performing-a-Comprehensive-Transthoracic-Echocardiographic-Examination-in-Adults.pdf` page 5 (matched: apical, four-chamber, Doppler, M-mode)
- `Guidelines-for-Performing-a-Comprehensive-Transthoracic-Echocardiographic-Examination-in-Adults_page_006.png` from `Guidelines-for-Performing-a-Comprehensive-Transthoracic-Echocardiographic-Examination-in-Adults.pdf` page 6 (matched: color)

## Source Provenance
### 2013_Performing-Comprehensive-TEE.pdf
- Path: `/Users/general/Library/CloudStorage/Box-Box/aether.lab/people/Oscar/Methods/codex-based-valvular-severity-classifier/CODEX-based-valvular-disease-severity-classifier/guidelines/2013_Performing-Comprehensive-TEE.pdf`
- Extraction method: `pdf_text`
- Relevant local text snippets:
  - linear measurement of the left atrium that has best correlated with transthoracic echocardio- graphic anteroposterior (parasternal LAX) measurements is taken from the ME A V LAX view (view #6) or the ME A V SAX view (view #10), measuring from the apex of the sector (i.e., the posterior wall of the left atrium
  - n be seen simultaneously. T urning the probe to the right from this view will typically image the mid-RV in SAX. 18. TG Apical SAX View (Video 18) From the TG midpapillary SAX view (0 /C14-20/C14), the probe is advanced while maintaining contact with the gastric wall, to obtain the TG apical SAX view. The
  - ansducer into the esophagus and stomach, and in adjusting probe position to obtain the necessary tomographic images and Doppler data. /C15Knowledge of infection control measures and electrical safety issues related to the use of TEE. /C15Proﬁciency in operating correctly the ultrasonographic instrument, in
  - eal ultrasound was ﬁrst reported in 1971 to measure ﬂow in the aortic arch. 1 This was followed in 1976 by its use with M-mode echocardiogra- phy 2 and then in 1977 by two- dimensional (2D) imaging using a mechanical scanning trans- ducer.3 The modern era of TEE really began in 1982, with the in- troducti
  - en saturation by pulse oximetry. Arterial blood with elevated methemoglobin levels has a characteristic chocolate-brown color compared with normal bright red oxygen-containing arterial blood. T reatment of this acquired disease is imperative because with severe methemoglobinemia (methemoglobin level > 55
  - sition regardless if viewed from the LA or the L V perspective (Figure 6). Wide-Angle 3D Mode. The focused wide sector (zoom view) per- mits a focused, wide-sector view of the MV apparatus from the an- nulus to the papillary muscle tips. It allows visualization of the mitral apparatus from the annulus t
### 2017VavularRegurgitationGuideline.pdf
- Path: `/Users/general/Library/CloudStorage/Box-Box/aether.lab/people/Oscar/Methods/codex-based-valvular-severity-classifier/CODEX-based-valvular-disease-severity-classifier/guidelines/2017VavularRegurgitationGuideline.pdf`
- Extraction method: `pdf_text`
- Relevant local text snippets:
  - window as systolic displacement of the mitral leaﬂet into the LA of at least 2 mm from the mitral annular plane. 95 If parasternal windows are of poor quality, the apical long-axis view can also be used, although the latter is less standardized and thus more variable. Diagnosis of MVP should be avoided in the
  - h the leaﬂets at different locations. A cross- commissural view (typically by TEE but approximated by the transthoracic apical two-chamber view) is good at identifying the lateral (P1) and medial (P3) scallops of the posterior leaﬂet and the middle (A2) anterior leaﬂet. The optimal view of the coaptation
  - tiple jets /C15 In order to measure it, convergence zone needs to be visualized Jet area /C15 Four chamber, RV inﬂow or subcostal views /C15 Qualitative /C15 Dependent on the driving pressure and jet direction /C15 Direction and shape of jet may overestimate (central entrainment) or underestimate (eccentric,
  - asternal window may be helpful. 182 b. Pulsed wave Doppler. Aortic diastolic ﬂow reversal: pulsed wave Doppler from the suprasternal window in the descending aorta often shows a brief early diastolic ﬂow reversal in normals. Holodiastolic ﬂow reversal is an abnormal ﬁnding ( Figure 22 ) and indicates at least m
  - 306 a. Valve structure and severity of regurgitation 306 b. Impact of regurgitation on cardiac remodeling 307 3. Color Doppler Imaging 307 a. Jet characteristics and jet area 308 b. V ena contracta 309 c. Flow convergence 309 4. Pulsed Doppler 310 a. Forward ﬂow 310 b. Flow reversal 310 5. Continuous Wave
  - on with echocardiography: a. Comprehensive imaging. All modalities included in the standard TTE evaluation inclusive of M-mode, 2D, and 3D where applicable, pulsed, color, continuous wave Doppler (CWD), and combined qual- itative and quantitative assessment contribute to valve regurgitation assessment. b.
  - maging 306 a. Valve structure and severity of regurgitation 306 b. Impact of regurgitation on cardiac remodeling 307 3. Color Doppler Imaging 307 a. Jet characteristics and jet area 308 b. V ena contracta 309 c. Flow convergence 309 4. Pulsed Doppler 310 a. Forward ﬂow 310 b. Flow reversal 310 5. Continu
  - w orientation is best achieved for aortic 28 or pulmonary regurgitation (PR), less for MR,16 and even less for TR. 29 A zoomed view is also indispensable to minimize the measurement inaccuracies for a width of a few milli- meters. VCA tracing requires 3D imaging and is achieved ofﬂine by reorienting ima
### Guidelines-for-Performing-a-Comprehensive-Transthoracic-Echocardiographic-Examination-in-Adults.pdf
- Path: `/Users/general/Library/CloudStorage/Box-Box/aether.lab/people/Oscar/Methods/codex-based-valvular-severity-classifier/CODEX-based-valvular-disease-severity-classifier/guidelines/Guidelines-for-Performing-a-Comprehensive-Transthoracic-Echocardiographic-Examination-in-Adults.pdf`
- Extraction method: `pdf_text`
- Relevant local text snippets:
  - n MS = Mitral stenosis MV = Mitral valve NCC = Noncoronary cusp PA = Pulmonary artery PFO = Patent foramen ovale PLAX = Parasternal long-axis PMPap = Posteromedial papillary muscle PMVL = Posterior leaﬂet mitral valve PR = Pulmonic valve regurgitation PRF = Pulse repetition frequency PSAX = Parasternal short-a
  - ler 12 7 . Doppler Tissue Imaging 15 C. Color Doppler Imaging 17 Abbreviations 2D = Two-dimensional 3C = Three-chamber (apical long axis) 3D = Three-dimensional 4C = Four-chamber 5C = Five-chamber A2C = Apical two-chamber A4C = Apical four-chamber Abd Ao = Abdominal aorta ALPap = Anterolateral papillary m
  - RV = Right ventricular RVIDd = Right ventricular internal dimension diastole RVOT = Right ventricular outﬂow tract SC = Subcostal SoVAo = Sinus of Valsalva SSN = Suprasternal notch STJ = Sinotubular junction SVC = Superior vena cava TAPSE = Tricuspid annular plane systolic excursion TGC = Time-gain compensat
  - icular internal dimension diastole RVOT = Right ventricular outﬂow tract SC = Subcostal SoVAo = Sinus of Valsalva SSN = Suprasternal notch STJ = Sinotubular junction SVC = Superior vena cava TAPSE = Tricuspid annular plane systolic excursion TGC = Time-gain compensation TR = Tricuspid valve regurgitation TTE =
  - olina; Salt Lake City, Utah; Ikoyi, Lagos, Nigeria; and Hartford, Connecticut Keywords: Transthoracic echocardiography, Doppler echocardiography, Color Doppler echocardiography, Comprehensive examination, Protocol TABLE OF CONTENTS I. Introduction 3 II. Nomenclature 4 A. Image Acquisition Windows 4 B. Scan
  - me 33 2. LA V olume 33 3. RV Linear Dimensions 33 4. RV Area 33 5. Right Atrial V olume 33 D. SC Views 37 1. IVC 37 VI. M-Mode Measurements 37 A. T APSE 37 B. IVC 37 C. A V 37 VII. CDI 37 A. RVOT, Pulmonary Valve, and PA 41 B. RV Inﬂow and TV 41 C. L V Inﬂow and MV 41 D. L VOT and A V 42 E. Aortic Arch 42
  - h; Ikoyi, Lagos, Nigeria; and Hartford, Connecticut Keywords: Transthoracic echocardiography, Doppler echocardiography, Color Doppler echocardiography, Comprehensive examination, Protocol TABLE OF CONTENTS I. Introduction 3 II. Nomenclature 4 A. Image Acquisition Windows 4 B. Scanning Maneuvers 5 C. Meas
  - 7317/$36.00 Copyright 2018 by the American Society of Echocardiography. https://doi.org/10.1016/j.echo.2018.06.004 1 9. Zoom/Magniﬁcation 8 10. Frame Rate 8 B. Spectral Doppler 8 1. V elocity Scale 8 2. Sweep Speed 8 3. Sample V olume Size 10 4. Wall Filters and Gain 10 5. Display Settings 12 6. Pulsed-
