from .cli import main
import multiprocessing

if __name__ == '__main__':
    multiprocessing.freeze_support()
    raise SystemExit(main())
