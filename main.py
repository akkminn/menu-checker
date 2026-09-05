import argparse
import sys

from utils.logger import log


def _serve(dev: bool = False) -> None:
    from config import HOST, PORT, SERVER_THREADS
    from scheduler import start_background, stop_background
    from fetcher.line_reader import app, shutdown_workers

    start_background()
    try:
        if dev:
            log.warning("Starting Flask DEV server — do not use this in production")
            app.run(host=HOST, port=PORT, threaded=True)
            return

        try:
            from waitress import serve
        except ImportError:
            log.error(
                "waitress is not installed — run: pip install -r requirements.txt "
                "(or pass --dev to use the development server)"
            )
            sys.exit(1)

        log.info("Line webhook server listening on %s:%d (%d threads)", HOST, PORT, SERVER_THREADS)
        log.info("Make sure ngrok or your reverse proxy forwards HTTPS to this port.")
        serve(app, host=HOST, port=PORT, threads=SERVER_THREADS)
    except KeyboardInterrupt:
        log.info("Interrupted — shutting down")
    finally:
        stop_background()
        shutdown_workers()


def main():
    parser = argparse.ArgumentParser(description="Burmese restaurant menu bot")
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="Run the Facebook pipeline once and exit (no server)",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Serve with the Flask development server instead of waitress",
    )
    args = parser.parse_args()

    if args.run_now:
        # One-shot Facebook pipeline run for testing
        log.info("Running pipeline immediately (--run-now flag)")
        from pipeline import run_pipeline
        run_pipeline()
        return

    # Production mode:
    # - BackgroundScheduler runs the Facebook pipeline daily at the configured time
    # - waitress serves the Line webhook (runs in the main thread)
    _serve(dev=args.dev)


if __name__ == "__main__":
    main()
