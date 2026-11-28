import React from 'react';
import styles from './HospitalAssistanceKnowledge.module.css';

/** Service information is coordination guidance, independent of any hospital API. */
export default function HospitalAssistanceKnowledge (): React.ReactElement {
  return <aside className={ styles.knowledge } aria-labelledby="ay-knowledge-title" tabIndex={ 0 }>
    <p className={ styles.eyebrow }>Before you submit</p>
    <h2 id="ay-knowledge-title">How Arogya Yatra works</h2>
    <section><h3>Your choice of hospital</h3>
      <p>Request assistance for any hospital you have in mind. Apollo is one option. You can name another hospital or ask WECARE to help you identify suitable options.</p>
      <p>Each hospital decides whether it can accept the appointment. Selecting a hospital does not mean it is a WECARE partner.</p>
    </section>
    <section><h3>What we can coordinate</h3>
      <ul><li>Consultation appointment enquiries.</li><li>Health-check enquiries and admission coordination.</li><li>Appointment-related travel planning, when requested.</li></ul>
      <p>Tell us the city, preferred date and any doctor or speciality preference. Flexible choices can help the team explore alternatives.</p>
    </section>
    <section><h3>After submission</h3>
      <ol><li>Save your request reference.</li><li>WECARE reviews the information and contacts you about next steps.</li><li>Check the hospital-confirmed doctor, date, time and charges before travelling.</li></ol>
      <p>A request receipt means we received your enquiry. It is not a hospital appointment confirmation.</p>
    </section>
    <section><h3>Service fee and hospital charges</h3>
      <p>No payment is collected when you submit this form.</p>
      <p>The WECARE base service fee is ₹550 plus 18% GST (₹649). Paid assistance follows the existing Express and Delight rules, with a 2.5% convenience fee and GST on that fee. We explain the scope and applicable total before you agree to a paid service.</p>
      <p>Hospital consultation, registration, health checks, treatment and travel charges are separate.</p>
    </section>
    <section><h3>Details to have ready</h3>
      <p>Use the patient’s correct name and a contact number with country code. For an existing hospital patient, keep the hospital’s patient reference ready for follow-up.</p>
      <p>Share only what is needed for coordination. This form does not require identity-document uploads or medical reports.</p>
    </section>
    <section><h3>Appointments and medical travel</h3>
      <p>Arogya Yatra helps coordinate appointments and related journeys. Clinical advice and treatment decisions belong to the qualified healthcare provider. This service does not sell medicines.</p>
    </section>
  </aside>;
}
