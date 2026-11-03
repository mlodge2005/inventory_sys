import { Link } from "react-router-dom";
import { ErrorNote, Loading, drawerList, formatWhen } from "../components/Feedback";
import { StatusBadge } from "../components/StatusBadge";
import { StockForm } from "../components/StockForm";
import { useLoad } from "../hooks/useLoad";
import { api } from "../services/api";
import type { Page, Stats, Transaction } from "../types";

export function DashboardPage() {
  const stats = useLoad(() => api<Stats>("/api/v1/stats"), []);
  const recent = useLoad(
    () => api<Page<Transaction>>("/api/v1/transactions?limit=8"),
    [],
  );

  return (
    <div className="stack">
      <h1>Dashboard</h1>
      <ErrorNote message={stats.error} />
      {stats.loading ? <Loading /> : null}
      {stats.data ? (
        <div className="stat-grid">
          <Link className="stat-card" to="/inventory">
            <strong>{stats.data.active_part_types}</strong>
            <span>Active part types</span>
          </Link>
          <Link className="stat-card" to="/drawers">
            <strong>{stats.data.occupied_slots}</strong>
            <span>Occupied drawers</span>
          </Link>
          <Link className="stat-card" to="/inventory">
            <strong>{stats.data.total_units}</strong>
            <span>Units on hand</span>
          </Link>
          <Link className="stat-card" to="/inventory?status=LOW_STOCK">
            <strong>{stats.data.low_stock_part_types}</strong>
            <span>Low stock</span>
          </Link>
          <Link className="stat-card" to="/inventory?status=OUT_OF_STOCK">
            <strong>{stats.data.out_of_stock_part_types}</strong>
            <span>Out of stock</span>
          </Link>
        </div>
      ) : null}

      <section className="card stack">
        <h2>Quick stock change</h2>
        <p className="muted">
          Search a part, choose the drawer, then confirm. Restocking does not change the baseline.
        </p>
        <StockForm
          onDone={() => {
            stats.reload();
            recent.reload();
          }}
        />
      </section>

      <section className="stack">
        <h2>Recent transactions</h2>
        <ErrorNote message={recent.error} />
        {recent.loading ? <Loading /> : null}
        <div className="table-wrap">
          <table className="responsive">
            <thead>
              <tr>
                <th>When</th>
                <th>Part</th>
                <th>Type</th>
                <th>Drawers</th>
                <th>Qty</th>
              </tr>
            </thead>
            <tbody>
              {(recent.data?.items ?? []).map((row) => (
                <tr key={row.id}>
                  <td data-label="When">{formatWhen(row.created_at)}</td>
                  <td data-label="Part">{row.part_name}</td>
                  <td data-label="Type">{row.transaction_type}</td>
                  <td data-label="Drawers">{drawerList(slotPair(row))}</td>
                  <td className="num" data-label="Qty">
                    {row.quantity_delta > 0 ? `+${row.quantity_delta}` : row.quantity_delta}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Link to="/transactions">Full history</Link>
      </section>
      <StatusHint />
    </div>
  );
}

function slotPair(row: Transaction): { slot_number: number; quantity: number }[] {
  const slots = [];
  if (row.from_slot_number) slots.push({ slot_number: row.from_slot_number, quantity: row.quantity });
  if (row.to_slot_number && row.to_slot_number !== row.from_slot_number) {
    slots.push({ slot_number: row.to_slot_number, quantity: row.quantity });
  }
  return slots;
}

function StatusHint() {
  return (
    <p className="muted">
      Status uses words and a marker: <StatusBadge status="IN_STOCK" /> <StatusBadge status="LOW_STOCK" />{" "}
      <StatusBadge status="OUT_OF_STOCK" />
    </p>
  );
}
