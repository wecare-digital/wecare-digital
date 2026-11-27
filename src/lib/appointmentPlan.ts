/** Preferences only. These dates and windows never represent provider inventory. */
export interface AppointmentPlan {
  hospitalId?: string;
  specialityId?: string;
  doctorId?: string;
  healthCheckId?: string;
  city: string;
  hospital: string;
  professional: string;
  patientMode: 'Telephone' | 'Camp';
  appointmentType: 'Consultation' | 'Health Checks' | 'Admission';
  speciality: string;
  healthCheck: string;
  time: string;
  userType: 'Registered User' | 'New User' | '';
  salutation: string;
  patientName: string;
  age: string;
  gender: string;
  area: string;
  email: string;
  mobile: string;
  uhid: string;
  pickup: string;
  remarks: string;
  pickupFrom: string;
  vehicleNo: string;
  arrivalDate: string;
  arrivalTime: string;
  attendants: string;
  journeyRemarks: string;
  shiftingFrom: string;
  shiftingDate: string;
  shiftingTime: string;
  healthDescription: string;
  ambulancePickup: string;
  ambulanceFrom: string;
  ambulanceArea: string;
  ambulanceDate: string;
  ambulanceTime: string;
  date: string;
}

export function indiaDate ( now = new Date() ): string {
  return new Intl.DateTimeFormat( 'en-CA', {
    timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit',
  } ).format( now );
}

export function appointmentPlanError ( plan: AppointmentPlan, today = indiaDate() ): string | null {
  if ( !plan.city.trim() ) return 'Enter your preferred city.';
  if ( plan.city.trim().length > 80 || plan.hospital.trim().length > 120 || plan.professional.trim().length > 120 ) {
    return 'Keep the city within 80 characters and hospital or professional within 120 characters.';
  }
  if ( !/^\d{4}-\d{2}-\d{2}$/.test( plan.date ) ) return 'Choose a preferred date.';
  const parsed = new Date( `${ plan.date }T00:00:00Z` );
  if ( !Number.isFinite( parsed.getTime() ) || parsed.toISOString().slice( 0, 10 ) !== plan.date ) return 'Choose a valid date.';
  if ( plan.date < today ) return 'Choose today or a future date. Dates use India Standard Time.';
  if ( !plan.hospital ) return 'Choose a hospital.';
  if ( plan.appointmentType === 'Health Checks' ) {
    if ( !plan.healthCheck.trim() ) return 'Enter the health check type.';
  } else if ( !plan.speciality.trim() || !plan.professional.trim() ) return 'Choose a speciality and doctor.';
  if ( !/^(?:0[1-9]|1\d|2[0-3]):(?:00|05|10|15|20|25|30|35|40|45|50|55)$/.test( plan.time ) ) return 'Choose a time in five-minute intervals, using 24-hour time.';
  if ( !plan.userType ) return 'Choose Registered User or New User.';
  if ( plan.userType === 'Registered User' ) {
    if ( !/^[6-9]\d{9}$/.test( plan.mobile ) && !/^[A-Z0-9]{2,12}\.\d{4,20}$/i.test( plan.uhid ) ) return 'Enter your 10-digit registered mobile number or UHID.';
  } else {
    if ( !plan.salutation || !plan.patientName.trim() || !plan.age || !plan.gender || !plan.area.trim() || !plan.pickup ) return 'Complete all required patient details.';
    if ( !/^\d{1,3}$/.test( plan.age ) || Number( plan.age ) > 120 ) return 'Enter an age between 0 and 120.';
    if ( !/^\+?[1-9]\d{9,14}$/.test( plan.mobile ) ) return 'Enter the patient mobile number with country code, for example 919999999999.';
    if ( plan.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test( plan.email ) ) return 'Enter a valid email address or leave it blank.';
    if ( plan.pickup === 'Yes' && ( !plan.pickupFrom || !plan.vehicleNo.trim() || !plan.arrivalDate || !plan.arrivalTime || !plan.attendants || !plan.journeyRemarks.trim() ) ) return 'Complete the pickup journey details.';
    if ( plan.appointmentType === 'Admission' ) {
      if ( !plan.shiftingFrom || !plan.shiftingDate || !plan.shiftingTime || !plan.healthDescription.trim() || !plan.ambulancePickup ) return 'Complete the admission transfer details.';
      if ( plan.ambulancePickup === 'Yes' && ( !plan.ambulanceFrom || !plan.ambulanceArea || !plan.ambulanceDate || !plan.ambulanceTime ) ) return 'Complete the ambulance pickup details.';
    }
  }
  return null;
}

export function appointmentPlanSummary ( plan: AppointmentPlan ): string {
  return [
    'Arogya Yatra — appointment preferences (not a confirmed booking)',
    `City: ${ plan.city.trim() }`,
    `Hospital: ${ plan.hospital.trim() || 'Help me choose' }`,
    `Patient mode: ${ plan.patientMode }`,
    `Appointment type: ${ plan.appointmentType }`,
    ...( plan.appointmentType === 'Health Checks' ? [ `Health check: ${ plan.healthCheck }` ] : [ `Speciality: ${ plan.speciality }`, `Doctor: ${ plan.professional }` ] ),
    `Preferred date: ${ plan.date } (India Standard Time)`,
    `Preferred time: ${ plan.time } (24-hour time)`,
    `User type: ${ plan.userType }`,
    'Provider availability, fees and confirmation still need to be checked.',
  ].join( '\n' );
}
