import numpy as np
from scipy.spatial.distance import squareform
from scipy.stats import pearsonr, zscore
from scipy.fftpack import fft, ifft
import itertools as it
import sys
import matplotlib.pyplot as plt


def errorfill(x, y, yerr, color=None, alpha_fill=0.3, ax=None):
    ax = ax if ax is not None else plt.gca()
    if np.isscalar(yerr) or len(yerr) == len(y):
        ymin = y - yerr
        ymax = y + yerr
    elif len(yerr) == 2:
        ymin, ymax = yerr
    ax.plot(x, y, color=color)
    ax.fill_between(x, ymax, ymin, color=color, alpha=alpha_fill)


def pieman_isc(data, pairwise=False, summary_statistic=None, verbose=True):
    """Intersubject correlation
    For each voxel or ROI, compute the Pearson correlation between each
    subject's response time series and other subjects' response time series.
    If pairwise is False (default), use the leave-one-out approach, where
    correlation is computed between each subject and the average of the other
    subjects. If pairwise is True, compute correlations between all pairs of
    subjects. If summary_statistic is None, return N ISC values for N subjects
    (leave-one-out) or N(N-1)/2 ISC values for each pair of N subjects,
    corresponding to the upper triangle of the pairwise correlation matrix
    (see scipy.spatial.distance.squareform). Alternatively, supply either
    np.mean or np.median to compute summary statistic of ISCs (Fisher Z will
    be applied and inverted if using mean). Input data should be a list 
    where each item is a time-points by voxels ndarray for a given subject.
    Multiple input ndarrays must be the same shape. If a single ndarray is
    supplied, the last dimension is assumed to correspond to subjects. If 
    only two subjects are supplied, simply compute Pearson correlation
    (precludes averaging in leave-one-out approach, and does not apply
    summary statistic.) Output is an ndarray where the first dimension is
    the number of subjects or pairs and the second dimension is the number
    of voxels (or ROIs).
        
    The implementation is based on the following publication:
    
    .. [Hasson2004] "Intersubject synchronization of cortical activity 
    during natural vision.", U. Hasson, Y. Nir, I. Levy, G. Fuhrmann,
    R. Malach, 2004, Science, 303, 1634-1640.
    Parameters
    ----------
    data : list or ndarray
        fMRI data for which to compute ISC
        
    pairwise : bool, default: False
        Whether to use pairwise (True) or leave-one-out (False) approach
        
    summary_statistic : None
        Return all ISCs or collapse using np.mean or np.median
    Returns
    -------
    iscs : subjects or pairs by voxels ndarray
        ISC for each subject or pair (or summary statistic) per voxel
    """
    
    # Convert list input to 3d and check shapes
    if type(data) == list:
        data_shape = data[0].shape
        for i, d in enumerate(data):
            if d.shape != data_shape:
                raise ValueError("All ndarrays in input list "
                                 "must be the same shape!")
            if d.ndim == 1:
                data[i] = d[:, np.newaxis]
        data = np.dstack(data)

    # Convert input ndarray to 3d and check shape
    elif type(data) == np.ndarray:
        if data.ndim == 2:
            data = data[:, np.newaxis, :]            
        elif data.ndim == 3:
            pass
        else:
            raise ValueError("Input ndarray should have 2 "
                             f"or 3 dimensions (got {data.ndim})!")

    # Infer subjects, TRs, voxels and print for user to check
    n_subjects = data.shape[2]
    n_TRs = data.shape[0]
    n_voxels = data.shape[1]
    if verbose:
        print(f"Assuming {n_subjects} subjects with {n_TRs} time points "
              f"and {n_voxels} voxel(s) or ROI(s).")
    
    # Loop over each voxel or ROI
    voxel_iscs = []
    for v in np.arange(n_voxels):
        voxel_data = data[:, v, :].T
        if n_subjects == 2:
            iscs = pearsonr(voxel_data[0, :], voxel_data[1, :])[0]
            summary_statistic = None
            if verbose:
                print("Only two subjects! Simply computing Pearson correlation.")
        elif pairwise:
            iscs = squareform(np.corrcoef(voxel_data), checks=False)
        elif not pairwise:
            iscs = np.array([pearsonr(subject,
                                      np.mean(np.delete(voxel_data,
                                                        s, axis=0),
                                              axis=0))[0]
                    for s, subject in enumerate(voxel_data)])
        voxel_iscs.append(iscs)
    iscs = np.column_stack(voxel_iscs)
    
    # Summarize results (if requested)
    if summary_statistic == np.mean:
        iscs = np.tanh(summary_statistic(np.arctanh(iscs), axis=0))[np.newaxis, :]
    elif summary_statistic == np.median:    
        iscs = summary_statistic(iscs, axis=0)[np.newaxis, :]
    elif not summary_statistic:
        pass
    else:
        raise ValueError("Unrecognized summary_statistic! Use None, np.median, or np.mean.")
    return iscs


def pieman_phaseshift_isc(data, pairwise=False, summary_statistic=np.median,
                   n_shifts=1000, return_distribution=False, random_state=None):
    
    """Phase randomization for one-sample ISC test
    
    For each voxel or ROI, compute the actual ISC and p-values
    from a null distribution of ISCs where response time series
    are phase randomized prior to computing ISC. If pairwise,
    apply phase randomization to each subject and compute pairwise
    ISCs. If leave-one-out approach is used (pairwise=False), only
    apply phase randomization to the left-out subject in each iteration
    of the leave-one-out procedure. Input data should be a list where
    each item is a time-points by voxels ndarray for a given subject.
    Multiple input ndarrays must be the same shape. If a single ndarray is
    supplied, the last dimension is assumed to correspond to subjects.
    Returns the observed ISC and p-values (two-tailed test). Optionally
    returns the null distribution of ISCs computed on phase-randomized
    data.
    
    This implementation is based on the following publications:
    .. [Lerner2011] "Topographic mapping of a hierarchy of temporal
    receptive windows using a narrated story.", Y. Lerner, C. J. Honey,
    L. J. Silbert, U. Hasson, 2011, Journal of Neuroscience, 31, 2906-2915.
    .. [Simony2016] "Dynamic reconfiguration of the default mode network
    during narrative comprehension.", E. Simony, C. J. Honey, J. Chen, O.
    Lositsky, Y. Yeshurun, A. Wiesel, U. Hasson, 2016, Nature Communications,
    7, 12141.
    Parameters
    ----------
    data : list or dict, time series data for multiple subjects
        List or dictionary of response time series for multiple subjects
    pairwise : bool, default:False
        Indicator of pairwise or leave-one-out, should match iscs variable
    summary_statistic : numpy function, default:np.median
        Summary statistic, either np.median (default) or np.mean
        
    n_shifts : int, default:1000
        Number of randomly shifted samples
        
    return_distribution : bool, default:False
        Optionally return the bootstrap distribution of summary statistics
        
    random_state = int, None, or np.random.RandomState, default:None
        Initial random seed
    Returns
    -------
    observed : float, observed ISC (without time-shifting)
        Actual ISCs
    p : float, p-value
        p-value based on time-shifting randomization test
        
    distribution : ndarray, time-shifts by voxels (optional)
        Time-shifted null distribution if return_bootstrap=True
    """

    # Convert list input to 3d and check shapes
    if type(data) == list:
        data_shape = data[0].shape
        for i, d in enumerate(data):
            if d.shape != data_shape:
                raise ValueError("All ndarrays in input list "
                                 "must be the same shape!")
            if d.ndim == 1:
                data[i] = d[:, np.newaxis]
        data = np.dstack(data)

    # Convert input ndarray to 3d and check shape
    elif type(data) == np.ndarray:
        if data.ndim == 2:
            data = data[:, np.newaxis, :]            
        elif data.ndim == 3:
            pass
        else:
            raise ValueError("Input ndarray should have 2 "
                             f"or 3 dimensions (got {data.ndim})!")

    # Infer subjects, TRs, voxels and print for user to check
    n_subjects = data.shape[2]
    n_TRs = data.shape[0]
    n_voxels = data.shape[1]
    
    # Get actual observed ISC
    observed = camcan_isc(data, pairwise=pairwise, summary_statistic=summary_statistic, verbose=False)
    
    # Iterate through randomized shifts to create null distribution
    distribution = []
    for i in np.arange(n_shifts):
        
        # Random seed to be deterministically re-randomized at each iteration
        if isinstance(random_state, np.random.RandomState):
            prng = random_state
        else:
            prng = np.random.RandomState(random_state)
            
        # Get randomized phase shifts
        if data.shape[0] % 2 == 0:
            # Why are we indexing from 1 not zero here? Vector is n_TRs / -1 long?
            pos_freq = np.arange(1, data.shape[0] // 2)
            neg_freq = np.arange(data.shape[0] - 1, data.shape[0] // 2, -1)
        else:
            pos_freq = np.arange(1, (data.shape[0] - 1) // 2 + 1)
            neg_freq = np.arange(data.shape[0] - 1, (data.shape[0] - 1) // 2, -1)

        phase_shifts = prng.rand(len(pos_freq), 1, n_subjects) * 2 * np.math.pi
        
        # In pairwise approach, apply all shifts then compute pairwise ISCs
        if pairwise:
        
            # Fast Fourier transform along time dimension of data
            fft_data = fft(data, axis=0)

            # Shift pos and neg frequencies symmetrically, to keep signal real
            fft_data[pos_freq, :, :] *= np.exp(1j * phase_shifts)
            fft_data[neg_freq, :, :] *= np.exp(-1j * phase_shifts)

            # Inverse FFT to put data back in time domain for ISC
            shifted_data = np.real(ifft(fft_data, axis=0))

            # Compute null ISC on shifted data for pairwise approach
            shifted_isc = camcan_isc(shifted_data, pairwise=True,
                              summary_statistic=summary_statistic, verbose=False)
        
        # In leave-one-out, apply shift only to each left-out participant
        elif not pairwise:
            
            # Roll subject axis in phaseshifts for loop
            phase_shifts = np.rollaxis(phase_shifts, 2, 0)
            
            shifted_isc = []
            for s, shift in enumerate(phase_shifts):
                
                # Apply FFT to left-out subject
                fft_subject = fft(data[:, :, s], axis=0)
                
                # Shift pos and neg frequencies symmetrically, to keep signal real
                fft_subject[pos_freq, :] *= np.exp(1j * shift)
                fft_subject[neg_freq, :] *= np.exp(-1j * shift)

                # Inverse FFT to put data back in time domain for ISC
                shifted_subject = np.real(ifft(fft_subject, axis=0))

                # Compute ISC of shifted left-out subject against mean of N-1 subjects
                nonshifted_mean = np.mean(np.delete(data, s, 2), axis=2)
                loo_isc = camcan_isc(np.dstack((shifted_subject, nonshifted_mean)), pairwise=False,
                              summary_statistic=None, verbose=False)
                shifted_isc.append(loo_isc)
                
            # Get summary statistics across left-out subjects
            if summary_statistic == np.mean:
                shifted_isc = np.tanh(np.mean(np.arctanh(np.dstack(shifted_isc)), axis=2))
            elif summary_statistic == np.median:
                shifted_isc = np.median(np.dstack(shifted_isc), axis=2)
                
        distribution.append(shifted_isc)
        
        # Update random state for next iteration
        random_state = np.random.RandomState(prng.randint(0, 2**32 - 1))
        
    # Convert distribution to numpy array
    distribution = np.vstack(distribution)
    assert distribution.shape == (n_shifts, n_voxels)

    # Get p-value for actual median from shifted distribution
    p = ((np.sum(np.abs(distribution) >= np.abs(observed), axis=0) + 1) /
          float((len(distribution) + 1)))[np.newaxis, :]
    
    if return_distribution:
        return observed, p, distribution
    elif not return_distribution:
        return observed, p