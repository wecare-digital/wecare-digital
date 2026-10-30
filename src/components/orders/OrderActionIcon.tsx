import React from 'react';

/**
 * The four Material Symbols Outlined supplied for the Orders interface.
 * Inline paths avoid an icon-font dependency and inherit the button's dark-green colour.
 */
type OrderIconName = 'copy_all' | 'download' | 'logout' | 'person';

const PATHS: Record<OrderIconName, string> = {
  copy_all: 'M6,36V33H9v3H6Zm0-8V25H9v3H6Zm0-8V17H9v3H6Zm8,24V41h3v3H14Zm3-8q-1.2,0-2.1-0.9T14,33V7q0-1.2,0.9-2.1T17,4H37q1.2,0,2.1,0.9T40,7V33q0,1.2-0.9,2.1T37,36H17Zm0-3H37V7H17V33Zm5,11V41h3v3H22ZM9,44q-1.24,0-2.12-0.88T6,41H9v3Zm21,0V41h3q0,1.25-0.88,2.13T30,44ZM6,12q0-1.24 0.88-2.12T9,9v3H6Zm21,8Z',
  download: 'M24,32.35L14.35,22.7l2.15-2.15l6,6V8h3V26.55l6-6l2.15,2.15L24,32.35ZM11,40q-1.2,0-2.1-0.9T8,37V29.85h3V37H37V29.85h3V37q0,1.2-0.9,2.1T37,40H11Z',
  logout: 'M9,42q-1.2,0-2.1-0.9T6,39V9Q6,7.8 6.9,6.9T9,6H23.95V9H9V39H23.95v3H9Zm24.3-9.25L31.15,30.6l5.1-5.1H18v-3H36.15l-5.1-5.1l2.15-2.15l8.8,8.8l-8.7,8.7Z',
  person: 'M18.6,21.85q-2.1-2.1-2.1-5.4t2.1-5.4T24,8.95t5.4,2.1t2.1,5.4t-2.1,5.4T24,23.95t-5.4-2.1ZM8,40V35.3q0-1.9 0.95-3.25T11.4,30q3.35-1.5 6.42-2.25T24,27t6.15,0.77T36.55,30q1.55,0.7 2.5,2.05T40,35.3V40H8Zm3-3H37V35.3q0-0.8-0.48-1.52T35.35,32.7q-3.2-1.55-5.85-2.13T24,30t-5.55,0.57T12.6,32.7q-0.7,0.35-1.15,1.07T11,35.3V37ZM27.23,19.67q1.27-1.27 1.27-3.22t-1.27-3.22T24,11.95t-3.22,1.28T19.5,16.45t1.28,3.22T24,20.95t3.23-1.28ZM24,16.45ZM24,37Z',
};

export default function OrderActionIcon (
  { name }: { name: OrderIconName },
): React.ReactElement {
  return (
    <svg aria-hidden="true" focusable="false" viewBox="0 0 48 48"
      width="28" height="28" fill="currentColor">
      <path d={ PATHS[ name ] } />
    </svg>
  );
}
