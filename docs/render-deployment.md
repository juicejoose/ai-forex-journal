# Run your journal on Render

The repository's `render.yaml` creates one Python web service that serves the React build and the API on the same HTTPS address. Render's Starter instance and a 1 GB persistent disk are selected. At the listed starting prices, the service and disk together cost about $7.25/month, before additional usage and OpenAI charges. Check the estimate shown by Render before creating the service.

## First deployment

1. Sign in to [Render](https://dashboard.render.com/register) using the GitHub account that owns this repository. Connect the repository when prompted. The deployment files must be on the repository's `main` branch.
2. In the Render dashboard, choose **New → Blueprint** and select the journal repository, branch `main`, and the root `render.yaml`. Choose a name for the Blueprint.
3. Enter these four values in Render's secret fields. Use a password manager for a long, unique ASCII `JOURNAL_PASSWORD`. The app's username is `journal`. For `OPENAI_API_KEY`, `OANDA_API_TOKEN`, and `OANDA_ACCOUNT_ID`, use the same credentials as your local backend. The Blueprint sets the OANDA practice URL. If your local app overrides `OPENAI_MODEL`, set the same optional backend variable in Render.
4. Review the **Starter** web service, its **1 GB** disk, and the estimated cost. Applying the Blueprint creates the paid service and starts the first deployment. Render runs the frontend build and starts the backend using the commands in `render.yaml`.
5. When the service shows **Live**, open its HTTPS address on your phone using cellular data. The browser prompts for username `journal` and your `JOURNAL_PASSWORD`. The homepage and `/api/journals` both require this sign-in. `/healthz` returns only `ok` for Render's health check.
6. If you want your Mac's journals and profiles on the server, transfer the database before creating entries on the hosted app. The hosted app reads `/var/data/journal.db` on its persistent disk.

## Bring your existing journals over

Do this once on a fresh hosted service. Restoring your local snapshot replaces the hosted database, including any entries previously created there.

1. On your Mac, from the repository root, create a consistent SQLite snapshot. The destination is in the project's ignored data folder. Verify it before transferring it.

   ```bash
   sqlite3 -readonly backend/data/journal.db ".backup 'backend/data/render-transfer.db'"
   sqlite3 -readonly backend/data/render-transfer.db 'PRAGMA quick_check;'
   ```

   The check should return `ok`.
2. Follow [Render's SSH setup](https://render.com/docs/ssh). In the service's **Connect → SSH** menu, copy the `user@host` portion for your service. From your Mac, upload the snapshot under a separate filename on the disk. Substitute the `user@host` from Render.

   ```bash
   scp backend/data/render-transfer.db user@host:/var/data/from-mac.db
   ```

3. In the Render service's **Shell**, on the fresh service, restore through SQLite and verify the copy. This avoids copying a database file over an open SQLite connection.

   ```bash
   sqlite3 -readonly /var/data/from-mac.db 'PRAGMA quick_check;'
   sqlite3 /var/data/journal.db '.restore /var/data/from-mac.db'
   sqlite3 -readonly /var/data/journal.db 'PRAGMA quick_check;'
   ```

   Proceed only if each check returns `ok` and the restore succeeds. Restart the service so startup migrations run against the restored database. Sign in, check one known daily journal, custom-range journal, and strategy profile if available. Subsequent phone and desktop visits to this hosted address use the same server database. Running the app locally continues to use your Mac's own database.

## Checks after deployment

- Open the site in a fresh private browser window. Cancelling the sign-in prompt should prevent access to both `/` and `/api/journals`.
- Sign in, create a test strategy profile, restart the service, and confirm that the profile is still visible. SQLite must be on the mounted path to survive restarts.
- Generate a journal for a known completed weekday to check both provider credentials from Render. This uses your OpenAI account as usual.

[Render Blueprints](https://render.com/docs/infrastructure-as-code) · [Persistent disks and file transfer](https://render.com/docs/disks) · [Pricing](https://render.com/pricing)
