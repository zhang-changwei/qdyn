import matplotlib as mpl
mpl.use('agg')
mpl.rcParams['axes.unicode_minus'] = False

import matplotlib.pyplot as plt
import numpy as np

#dir_list = ('f', 'ya', 'normal')
#label_list = ('Ferro', 'F2%', 'stable')

#dir_list = ('new')
#label_list = ('100')

#fig = plt.figure()
#fig.set_size_inches(4.8, 3.0)

#ax  = plt.subplot()

#ndirs = len(dir_list)
#for ii in range(ndirs):
#    Y = np.loadtxt(dir_list[ii] + "/5_NAMD/" + 'NATXT')
#    nac = Y[:500,1]
#    time = np.arange(np.size(nac))
#    line, = ax.plot(time, nac, label=label_list[ii])
    
#    rms = np.sqrt(np.mean(np.square(nac)))
#    print("The RMS of the %s is: %f" % (label_list[ii], rms))
# ax.set_xlim(0, np.size(X)/1e6)
# ax.set_ylim(0.95, 1.0)

Y = np.loadtxt("NATXT")
Nac = np.abs(Y[:,1])
#print(np.argmax(Nac))
#print(Nac[np.argmax(Nac)])
#nac = Y[:500,1]
#time = np.arange(np.size(nac))
#line, = ax.plot(time, nac)

rms = np.sqrt(np.mean(np.square(Nac)))
print("The RMS of the stable is: %f \n" % rms)


#ax.set_xlabel('Time [fs]', labelpad=5)
#ax.set_ylabel('NAC', labelpad=5)

#ax.legend()

#plt.tight_layout(pad=0.2)
#plt.savefig('NAC.png', dpi=720)
Wht = np.load('../all_wht.npy')
#Enr = np.load('../all_en.npy')
order = np.argsort(Nac)

for i in range(20):
      a = order[-i-1]
      print("The step is %d" % (a+2))
      print("NAC is %f" % Nac[a])
      print("The down weight of 936 is %f" % Wht[a+1,935])
      print("The down weight of 937 is %f \n" % Wht[a+1,936])
      #print(Enr[a+1,935])

print("NACmin")
for i in range(20):
      a = order[i]
      print("The step is %d" % (a+2))
      print("NAC is %f" % Nac[a])
      print("The down weight of 936 is %f" % Wht[a+1,935])
      print("The down weight of 937 is %f \n" % Wht[a+1,936])
