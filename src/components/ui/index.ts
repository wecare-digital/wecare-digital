/**
 * UI Components - WECARE.DIGITAL
 * Unified component exports
 */

export { default as Button } from './Button';
export type { ButtonVariant, ButtonSize, ButtonIcon } from './Button';

export { default as IconButton } from './IconButton';
export type { IconButtonSize } from './IconButton';

export { default as Spinner } from './Spinner';

export { default as Tabs } from './Tabs';
export type { TabItem } from './Tabs';

export { default as EmptyState } from './EmptyState';

export { default as Breadcrumbs } from './Breadcrumbs';

export { default as KeyboardShortcuts, useKeyboardShortcutsModal } from './KeyboardShortcuts';

export { default as Modal } from './Modal';

export { default as Pagination } from './Pagination';

export { default as Table } from './Table';

/**
 * Layer 2 - our own menus. Popover is the positioning-and-dismissal primitive; Select is the
 * first consumer. NO CALL SITE USES THEM YET, deliberately: the components land and are
 * proven in isolation before 159 of them depend on the contract.
 */
export { default as Popover } from './Popover';
export type { PopoverProps, PopoverLayer, PopoverDismissReason } from './Popover';

export { default as Select } from './Select';
export type { SelectProps, SelectOption, SelectGroup } from './Select';

/**
 * The date / time / colour pickers, all on Popover. Each one EMITS AND ACCEPTS THE SAME STRING
 * ITS NATIVE COUNTERPART DOES - `YYYY-MM-DD`, `HH:MM`, `YYYY-MM-DDTHH:MM`, `#rrggbb` - which is
 * what keeps every migrated call site's state shape, payload and validation unchanged and makes
 * a revert per call site a two-line edit.
 */
export { default as DateField } from './DateField';
export type { DateFieldProps } from './DateField';

export { default as TimeField } from './TimeField';
export type { TimeFieldProps } from './TimeField';

export { default as DateTimeField } from './DateTimeField';
export type { DateTimeFieldProps } from './DateTimeField';

export { default as ColorField } from './ColorField';
export type { ColorFieldProps, ColorSwatch } from './ColorField';
