## GCLogger

### Installation/Usage
Logging metrics/analytics from within notebooks.

For basic usage, install examples-utils and then import:
```
from examples_utils.notebook_logging.gc_logger import GCLogger
```

And to start the logging:
```
GCLogger.start_logging()
```

This will startup background processes that log and upload system, IPU and notebook usage information.

To stop all logging/uploading, run:
```
GCLogger.stop_logging()
```

### Disclaimer

On first importing and generating a GCLogger object, the following disclaimer is presented to the user within the stdout of a cell in a notebook:
```
============================================================================================================================================
Graphcore would like to collect information about the applications and code being run in this notebook, as well as the system it's being run 
on to improve usability and support for future users. The information will be anonymised and sent to Graphcore 

You can disable this at any time by running `GCLogger.stop_logging()'`.

Unless logging is disabled, the following information will be collected:
	- User progression through the notebook
	- Notebook details: number of cells, code being run and the output of the cells
	- ML application details: Model information, performance, hyperparameters, and compilation time
	- Environment details
	- System performance: IO, memory and host compute performance

You can view the information being collected at: /notebooks/gc_logs/<timestamp>
=============================================================================================================================================
```

This is meant as a prototype to demonstrate how the capability could be implemented.
