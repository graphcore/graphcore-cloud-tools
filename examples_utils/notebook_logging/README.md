## GCLogger

### Installation/Usage
Logging metrics/analytics from within notebooks.

For basic usage, install examples-utils and then import:
```
from examples_utils import notebook_logging
```

And to start the logging:
```
`%load_ext gc_logger`
```

This will startup background processes that log and upload system, IPU and notebook usage information.

To stop all logging/uploading, run:
```
`%unload_ext gc_logger`
```
from any cell in the notebook

### Disclaimer

On first importing and generating a GCLogger object, the following disclaimer is presented to the user within the stdout of a cell in a notebook:
```
============================================================================================================================================
Graphcore would like to collect information about the applications and code being run in this notebook, as well as the system it's being run 
on to improve usability and support for future users. The information will be anonymised and sent to Graphcore 

You can disable this at any time by running `%unload_ext gc_logger` from any cell.

Unless logging is disabled, the following information will be collected:
	- User progression through the notebook
	- Notebook details: number of cells, code being run and the output of the cells
	- ML application details: Model information, performance, hyperparameters, and compilation time
	- Environment details
	- System performance: IO, memory and host compute performance
=============================================================================================================================================
```

This is meant as a prototype to demonstrate how the capability could be implemented.
