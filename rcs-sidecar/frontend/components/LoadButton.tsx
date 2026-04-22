export default function LoadButton({ calibration }: { calibration: any }) {
  return (
    <div className="mt-4 p-4 border border-indigo-500/30 bg-indigo-500/10 rounded-xl">
      <button 
        onClick={() => console.log('Calibration loaded:', calibration)}
        className="w-full py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg transition"
      >
        Load into Simulation &rarr;
      </button>
      <p className="text-xs text-center text-gray-400 mt-2">
        Ready with {calibration.segments?.length || 0} segments.
      </p>
    </div>
  )
}
