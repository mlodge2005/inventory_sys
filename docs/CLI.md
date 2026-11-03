# Terminal

The command is `inventory`. After installation it is on `/usr/local/bin/inventory` and uses the same `InventoryService` as the website. It reads `/etc/cyberdeck-inventory.env`, so it sees the production database even when you do not pass a URL.

Your user must be in the `cyberdeck` group. The installer adds the user who ran `sudo`. Log out and back in once so the group applies. The database, WAL, and shared-memory files must be mode `0660` and group `cyberdeck`. Membership alone is not enough when those files are still mode `0600`: restart `cyberdeck-inventory.service`, or re-run `scripts/install.sh` or `scripts/update.sh`, and the file owner repairs them in place. Do not run `inventory` as root.

With no arguments in an interactive terminal, a menu opens:

```text
CYBERDECK INVENTORY
1. View Inventory
2. Search Parts
3. Manage Stock
4. Create / Edit Part
5. Manage Drawers
6. Low Stock Report
7. Recent Transactions
8. Website QR Code
9. Settings
0. Exit
```

Direct commands:

```bash
inventory list
inventory search "M3"
inventory slot 110
inventory add 110 25
inventory remove 110 5
inventory low
inventory history
inventory qr
inventory status
inventory help
```

`add 110 25` and `remove 110 5` are valid only when that drawer holds exactly one part type. If it holds screws and nuts, the command exits 4 and prints both choices. Name the part:

```bash
inventory add --slot 110 --part M3-SCREW --quantity 25
inventory remove --slot 110 --part M3-SCREW --quantity 5
inventory transfer --from 110 --to 111 --part M3-SCREW --quantity 10
```

`--part` accepts an id, an exact SKU, an exact name, or a unique substring.

```bash
inventory slot create 110 --label Screws
inventory slot edit 110 --number 210
inventory slot archive 110
inventory slot delete 110 --confirm-remove-stock
inventory part create --name "M3 screw" --sku M3-SCREW --initial 100 --allocate 110:100
inventory part show M3-SCREW
inventory part baseline M3-SCREW --initial 80
inventory export parts
inventory import parts --file parts.csv
inventory import parts --file parts.csv --commit
inventory init
inventory devseed
```

`part create --initial` sets the baseline. `--allocate 110:100` is the physical stock. `part baseline` changes the alert reference and writes an audit row. It does not move pieces. `devseed` loads labeled DEMO rows and refuses `INVENTORY_ENVIRONMENT=production`. `init` migrates the database and does not insert parts.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | Unexpected error |
| 2 | Usage or validation |
| 3 | Not found |
| 4 | Ambiguous part |
| 5 | Conflict, negative stock, not empty, history, or archived |

## QR code

```bash
inventory qr
inventory qr --ascii
inventory qr --url http://100.64.1.2:8765
```

The command draws a QR code locally and prints the URL underneath. It does not contact a QR website. Address choice:

1. `--url`
2. `INVENTORY_PUBLIC_URL`
3. Settings preferred public URL
4. The index you pick when more than one address exists and a terminal is attached
5. The only detected address
6. Otherwise the first Ethernet, Wi-Fi, hotspot, or Tailscale address, in that order

The default route is not assumed to be the address other devices should open. Hotspot addresses such as `10.42.0.1` and `192.168.4.1` are labeled separately from LAN addresses. Tailscale is recognized by the interface name.
