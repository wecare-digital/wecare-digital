/** Observed in the authorized Apollo IC portal on 2026-11-27.
 * Snapshot labels only: not live availability or a substitute for server-side provider validation.
 * Doctor options below belong only to hospital 2, speciality 260.
 */
export const APOLLO_HOSPITALS = [
  ['2', 'Apollo Hospitals Greams Road Chennai'], ['22', 'Apollo Cancer Institutes'],
  ['25', 'Apollo Firstmed Hospital'], ['28', 'Apollo Children Hospital Chennai'],
  ['65', 'Apollo Hospitals Tondiarpet'], ['66', 'Apollo City Center Hospital Sowcarpet'],
  ['81', 'The Apollo Heart Centre'], ['119', 'Apollo Speciality Hospitals Vanagaram'],
  ['126', 'Apollo Cradle & Childrens Hospital Karapakkam'], ['134', 'Apollo Speciality Hospitals O M R'],
  ['202', 'Apollo Womens Hospital'], ['330', 'Apollo Proton Cancer Centre'],
] as const;

export const GREAMS_SPECIALITIES = [
  'Allergic Medicine', 'Andrologist', 'Bariatrics Surgery', 'Breast Surgery',
  'Cardiac Pacing & Electrophysiology', 'Cardio Thoracic Surgery', 'Cardiology',
  'Cardiothoracic & Vascular Surgery', 'Colorectal Surgery', 'Critical Care', 'Dental',
  'Dermatology', 'Diabetology', 'Endocrine Surgery', 'Endocrinology', 'Ent',
  'Gastroenterology', 'General & Lap Surgery', 'General Medicine', 'General Surgery',
  'General Surgery & Laproscopic Surgery', 'Genetic', 'Geriatrics', 'Haematology',
  'Head & Neck Surgeon', 'Hepatology', 'Infectious Diseases', 'Internal Medicine',
  'Interventional Cardiologist', 'Interventional Radiologist', 'Liver Transplant',
  'Maxillo Facial Surgeon', 'Medical Gastroenterology', 'Medical Oncology', 'Nephrology',
  'Neurology', 'Neurosurgery', 'Nuclear Medicine', 'Nutrition & Dietetics',
  'Obstetrics & Gynecology', 'Opthalmology', 'Oral & Maxilofacial Surgery',
  'Orthopaedic Surgeon', 'Orthopaedics', 'Pain Management',
  'Physical Medicine & Rehabilitation', 'Plastic Surgery', 'Psychiatry', 'Pulmonology',
  'Radiation Oncology', 'Respiratory Medicine', 'Rheumatology', 'Sexual Medicine',
  'Spine Surgery', 'Surgical Gastroenterology', 'Surgical Oncology', 'Thoracic Surgery',
  'Transplant Surgery', 'Urogynaecology', 'Urology', 'Vascular Surgery',
] as const;

export const GREAMS_GENERAL_SURGEONS = [
  'Dr Balachandar Kariappa Reddy', 'Dr Jameel Akhter', 'Dr N Shivakumar',
  'Dr Pandiaraj R A', 'Dr Preethi mrinalini K', 'Dr Premkumar Balachandran',
  'Dr Prithviraj T', 'Dr Raghunath K J', 'Dr Ramamoorthy N',
  'Dr Venkatasubramanian Rangarajan',
] as const;
