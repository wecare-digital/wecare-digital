import test from 'node:test';
import assert from 'node:assert/strict';
import { appointmentPlanError, appointmentPlanSummary, indiaDate } from '../src/lib/appointmentPlan.ts';

const plan = {
  city: ' Chennai ', hospital: 'Apollo Hospitals Greams Road Chennai', professional: 'Dr Balachandar Kariappa Reddy',
  date: '2026-11-30', time: '18:50', patientMode: 'Telephone', appointmentType: 'Consultation',
  speciality: 'General Surgery', healthCheck: '', userType: 'Registered User',
  mobile: '9999999999', uhid: '', salutation: '', patientName: '', age: '', gender: '', area: '', email: '', pickup: '', remarks: '',
};

test('India calendar date rolls over independently of the UTC date', () => {
  assert.equal(indiaDate(new Date('2026-11-27T18:29:59Z')), '2026-11-27');
  assert.equal(indiaDate(new Date('2026-11-27T18:30:00Z')), '2026-11-28');
});

test('preferences require a city and a real date that has not passed', () => {
  const validate = changes => appointmentPlanError({ ...plan, ...changes }, '2026-11-28');
  assert.equal(validate({}), null);
  assert.match(validate({ city: '   ' }), /city/);
  assert.match(validate({ city: 'a'.repeat(81) }), /80 characters/);
  assert.match(validate({ date: '' }), /date/);
  assert.match(validate({ date: '2026-02-30' }), /valid date/);
  assert.match(validate({ date: '2026-11-27' }), /future date/);
  assert.equal(validate({ date: '2028-02-29' }), null);
});

test('review text preserves preferences and never represents them as a reservation', () => {
  const summary = appointmentPlanSummary(plan);
  assert.ok(summary.includes('not a confirmed booking'));
  assert.ok(summary.includes('City: Chennai\n'));
  assert.ok(summary.includes('Hospital: Apollo Hospitals Greams Road Chennai'));
  assert.ok(!summary.includes('9999999999'));
  assert.ok(summary.includes('Doctor: Dr Balachandar Kariappa Reddy'));
  assert.ok(summary.includes('18:50 (24-hour time)'));
  assert.ok(summary.includes('2026-11-30 (India Standard Time)'));
  assert.ok(summary.includes('availability, fees and confirmation still need to be checked'));
});

test('exact time and patient lookup cannot be skipped', () => {
  const validate = changes => appointmentPlanError({ ...plan, ...changes }, '2026-11-28');
  assert.match(validate({ time: '18:51' }), /five-minute/);
  assert.match(validate({ time: '00:50' }), /five-minute/);
  assert.match(validate({ userType: '' }), /Registered User/);
  assert.match(validate({ mobile: '', uhid: '' }), /mobile number or UHID/);
  assert.equal(validate({ mobile: '', uhid: 'APX1.0000000000' }), null);
});

test('new patients require their own details; health checks do not require a doctor', () => {
  const patient = { ...plan, userType: 'New User', salutation: 'Mr.', patientName: 'Synthetic Patient', age: '45', gender: 'Male', area: 'Test area', mobile: '919999999999', pickup: 'No' };
  assert.equal(appointmentPlanError(patient, '2026-11-28'), null);
  assert.match(appointmentPlanError({ ...patient, age: '121' }, '2026-11-28'), /age/);
  assert.match(appointmentPlanError({ ...patient, patientName: '' }, '2026-11-28'), /required patient/);
  assert.equal(appointmentPlanError({ ...patient, appointmentType: 'Health Checks', professional: '', speciality: '', healthCheck: 'Requested check' }, '2026-11-28'), null);
  const summary = appointmentPlanSummary(patient);
  for (const privateValue of ['Synthetic Patient', 'Test area', '919999999999']) assert.ok(!summary.includes(privateValue));
});

test('admission and vehicle requests require their conditional transport details', () => {
  const patient = { ...plan, userType: 'New User', salutation: 'Mr.', patientName: 'Synthetic Patient', age: '45', gender: 'Male', area: 'Test area', mobile: '919999999999', pickup: 'No', appointmentType: 'Admission' };
  assert.match(appointmentPlanError(patient, '2026-11-28'), /admission transfer/);
  const admission = { ...patient, shiftingFrom: 'Home', shiftingDate: '2026-11-30', shiftingTime: '17:00', healthDescription: 'Synthetic fixture', ambulancePickup: 'No' };
  assert.equal(appointmentPlanError(admission, '2026-11-28'), null);
  assert.match(appointmentPlanError({ ...admission, ambulancePickup: 'Yes' }, '2026-11-28'), /ambulance pickup/);
  assert.match(appointmentPlanError({ ...admission, pickup: 'Yes' }, '2026-11-28'), /pickup journey/);
  assert.ok(!appointmentPlanSummary(admission).includes('Synthetic fixture'));
});
