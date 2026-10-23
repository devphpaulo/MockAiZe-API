from mockaize_api.windows_service import dispatch

if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    import sys
    if '--run' in sys.argv:
        import argparse
        from pathlib import Path
        from mockaize_api.runtime import serve
        parser = argparse.ArgumentParser()
        parser.add_argument('--run', action='store_true')
        parser.add_argument('--config', type=Path, required=True)
        arguments = parser.parse_args()
        serve(arguments.config)
    else:
        dispatch()
