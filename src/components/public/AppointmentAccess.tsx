import React from 'react';
import AppointmentPlanner from './AppointmentPlanner';

/** The form is public; genuine WhatsApp authentication is checked at submission. */
export default function AppointmentAccess (): React.ReactElement {
  return <AppointmentPlanner />;
}
