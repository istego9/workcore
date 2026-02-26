import { ScrollArea, Table, Text } from '@mantine/core';
import type { WidgetComponent } from '../../protocol/types';

type DataTableProps = {
  component: WidgetComponent;
};

export function DataTable({ component }: DataTableProps) {
  const columns = Array.isArray(component.columns) ? component.columns : [];
  const rows = Array.isArray(component.rows) ? component.rows : [];

  if (!columns.length) {
    return (
      <Text c="dimmed" size="sm">
        DataTable: columns are missing
      </Text>
    );
  }

  return (
    <ScrollArea.Autosize mah={300}>
      <Table striped withTableBorder withColumnBorders horizontalSpacing="sm" verticalSpacing="xs">
        <Table.Thead>
          <Table.Tr>
            {columns.map((column) => (
              <Table.Th key={column.key} style={{ textAlign: column.align || 'left' }}>
                {column.label}
              </Table.Th>
            ))}
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((row, rowIndex) => (
            <Table.Tr key={`row-${rowIndex}`}>
              {columns.map((column) => (
                <Table.Td key={`${rowIndex}-${column.key}`} style={{ textAlign: column.align || 'left' }}>
                  {String(row[column.key] ?? '')}
                </Table.Td>
              ))}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </ScrollArea.Autosize>
  );
}
