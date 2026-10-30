import React from 'react';

/**
 * The four Material Symbols Outlined supplied for the Orders interface.
 * Inline paths avoid an icon-font dependency and inherit the button's lime colour.
 */
type OrderIconName = 'copy_all' | 'download' | 'logout' | 'account_circle';

const PATHS: Record<OrderIconName, string> = {
  copy_all: 'M6,36V33H9v3H6Zm0-8V25H9v3H6Zm0-8V17H9v3H6Zm8,24V41h3v3H14Zm3-8q-1.2,0-2.1-0.9T14,33V7q0-1.2,0.9-2.1T17,4H37q1.2,0,2.1,0.9T40,7V33q0,1.2-0.9,2.1T37,36H17Zm0-3H37V7H17V33Zm5,11V41h3v3H22ZM9,44q-1.24,0-2.12-0.88T6,41H9v3Zm21,0V41h3q0,1.25-0.88,2.13T30,44ZM6,12q0-1.24 0.88-2.12T9,9v3H6Zm21,8Z',
  download: 'M24,32.35L14.35,22.7l2.15-2.15l6,6V8h3V26.55l6-6l2.15,2.15L24,32.35ZM11,40q-1.2,0-2.1-0.9T8,37V29.85h3V37H37V29.85h3V37q0,1.2-0.9,2.1T37,40H11Z',
  logout: 'M9,42q-1.2,0-2.1-0.9T6,39V9Q6,7.8 6.9,6.9T9,6H23.95V9H9V39H23.95v3H9Zm24.3-9.25L31.15,30.6l5.1-5.1H18v-3H36.15l-5.1-5.1l2.15-2.15l8.8,8.8l-8.7,8.7Z',
  account_circle: 'M11.1,35.25q3.15-2.2 6.25-3.38T24,30.7t6.68,1.18t6.28,3.38q2.2-2.7 3.13-5.45T41,24q0-7.25-4.88-12.13T24,7T11.88,11.88T7,24q0,3.05 0.95,5.8t3.15,5.45Zm8.02-11.73q-1.97-1.98-1.97-4.88t1.97-4.88T24,11.8t4.88,1.98t1.98,4.88t-1.98,4.88T24,25.5t-4.88-1.98ZM24,44q-4.1,0-7.75-1.58t-6.38-4.3t-4.3-6.38T4,24q0-4.15 1.58-7.78t4.3-6.35t6.38-4.3T24,4q4.15,0 7.78,1.57t6.35,4.3t4.3,6.35T44,24q0,4.1-1.57,7.75t-4.3,6.38t-6.35,4.3T24,44Zm5.38-3.8q2.63-0.8 5.18-2.8q-2.55-1.8-5.2-2.75T24,33.7t-5.35,0.95t-5.2,2.75q2.55,2 5.17,2.8T24,41t5.38-0.8Zm-2.6-18.78q1.07-1.07 1.07-2.77t-1.07-2.77T24,14.8t-2.77,1.08t-1.07,2.77t1.07,2.77T24,22.5t2.78-1.08ZM24,18.65Zm0,18.7Z',
};

export default function OrderActionIcon (
  { name }: { name: OrderIconName },
): React.ReactElement {
  return (
    <svg aria-hidden="true" focusable="false" viewBox="0 0 48 48"
      width="24" height="24" fill="currentColor"
      stroke="var(--public-brand-green)" strokeWidth="1.5" strokeLinejoin="round">
      <path d={ PATHS[ name ] } />
    </svg>
  );
}
