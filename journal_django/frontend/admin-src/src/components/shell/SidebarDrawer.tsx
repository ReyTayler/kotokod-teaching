import * as RadixDialog from '@radix-ui/react-dialog';
import { Sidebar } from './Sidebar';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Мобильная навигация: тот же сайдбар, выезжающий слева поверх контента.
 *
 * Закрытие по Esc, ловушку фокуса, возврат фокуса на бургер, блокировку
 * прокрутки страницы и aria-разметку берёт на себя Radix Dialog — писать это
 * руками не нужно.
 */
export function SidebarDrawer({ open, onOpenChange }: Props) {
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="sidebar-drawer-overlay" />
        <RadixDialog.Content className="sidebar-drawer" aria-describedby={undefined}>
          <RadixDialog.Title className="sr-only">Меню разделов</RadixDialog.Title>
          <Sidebar onClose={() => onOpenChange(false)} />
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}
