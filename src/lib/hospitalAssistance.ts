/** Coordination preferences, never provider inventory or a confirmed appointment. */
export const HOSPITAL_CHOICES = [ 'Apollo Hospitals', 'Another hospital', 'Help me choose' ] as const;
export const REQUEST_TYPES = [ 'Consultation', 'Health check', 'Admission assistance' ] as const;
export const TIME_WINDOWS = [ 'Flexible', 'Morning', 'Afternoon', 'Evening' ] as const;

export interface HospitalAssistanceRequest {
  hospitalChoice: typeof HOSPITAL_CHOICES[number];
  hospitalName: string;
  city: string;
  appointmentType: typeof REQUEST_TYPES[number];
  speciality: string;
  doctor: string;
  preferredDate: string;
  preferredTime: typeof TIME_WINDOWS[number];
  patientName: string;
  mobile: string;
  email: string;
  notes: string;
  consent: boolean;
}
export interface AssistanceReceipt {
  requestId: string;
  status: 'REQUESTED';
  createdAt: number;
  appointmentConfirmed: false;
}
export function isAssistanceReceipt ( value: unknown ): value is AssistanceReceipt {
  if ( !value || typeof value !== 'object' ) return false;
  const row = value as Partial<AssistanceReceipt>;
  return typeof row.requestId === 'string' && /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test( row.requestId ) &&
    row.status === 'REQUESTED' && row.appointmentConfirmed === false && typeof row.createdAt === 'number' && Number.isSafeInteger( row.createdAt );
}
